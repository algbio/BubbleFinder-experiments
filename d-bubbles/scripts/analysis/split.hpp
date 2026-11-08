// Find the component between two boundaries.
#ifndef D_BUBBLE_NATIVE_SPLIT_INDEX_HPP
#define D_BUBBLE_NATIVE_SPLIT_INDEX_HPP
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace vg_native_split {
constexpr uint32_t NONE = UINT32_MAX;

inline void need(bool p, const char* why)
{
    if (!p)
        throw std::runtime_error(why);
}

struct Range
{
    uint32_t begin = 0, end = 0;
};

inline bool has(Range p, uint32_t x)
{
    return p.begin <= x && x < p.end;
}

struct Graph
{
    std::vector<uint8_t> present;
    std::vector<uint32_t> offset, neighbor;
    uint64_t gray_records = 0;

    uint32_t nodes() const
    {
        return uint32_t(present.size());
    }

    uint32_t poles() const
    {
        return 2 * nodes();
    }

    // Visit the same links in both passes.
    template <class Enumerate> static Graph build(std::vector<uint8_t> present, Enumerate enumerate)
    {
        need(!present.empty() && present.size() <= UINT32_MAX / 2,
                "the graph is empty or has too many nodes for 32 bit side IDs");
        Graph g;
        g.present = std::move(present);
        g.offset.assign(uint64_t(g.poles()) + 1, 0);
        for (uint8_t p : g.present)
            need(p < 2, "node presence must be zero or one");
        uint64_t links = 0, incidences = 0;
        enumerate([&](uint32_t a, uint32_t b) {
            need(a < g.poles() && b < g.poles() && g.present[a / 2] && g.present[b / 2],
                 "edge end is outside the graph");
            need(incidences <= UINT32_MAX - 2 && g.offset[a + 1] < UINT32_MAX && g.offset[b + 1] < UINT32_MAX,
                 "too many edge entries for 32 bit offsets");
            ++g.offset[a + 1];
            ++g.offset[b + 1];
            incidences += 2;
            ++links;
        });
        for (uint32_t p = 0; p < g.poles(); ++p) {
            uint64_t next = uint64_t(g.offset[p]) + g.offset[p + 1];
            need(next <= UINT32_MAX, "edge offset exceeds 32 bit IDs");
            g.offset[p + 1] = uint32_t(next);
        }
        need(g.offset.back() == incidences, "edge offsets do not match the counted edge entries");
        g.neighbor.resize(incidences);
        auto cursor = g.offset;
        uint64_t again = 0;
        enumerate([&](uint32_t a, uint32_t b) {
            need(a < g.poles() && b < g.poles() && g.present[a / 2] && g.present[b / 2],
                 "second edge pass found a missing node side");
            need(uint64_t(cursor[a]) + (a == b ? 1u : 0u) < g.offset[a + 1] && cursor[b] < g.offset[b + 1],
                 "second pass found more edges than the first");
            g.neighbor[cursor[a]++] = b;
            g.neighbor[cursor[b]++] = a;
            ++again;
        });
        need(again == links, "edge count changed between passes");
        for (uint32_t p = 0; p < g.poles(); ++p) {
            need(cursor[p] == g.offset[p + 1],
                    "node side degree changed between passes");
            std::sort(g.neighbor.begin() + g.offset[p], g.neighbor.begin() + g.offset[p + 1]);
        }
        g.gray_records = links;
        return g;
    }

    bool gray(uint32_t a, uint32_t b) const
    {
        need(a < poles() && b < poles(), "requested node side is outside the graph");
        return std::binary_search(neighbor.begin() + offset[a], neighbor.begin() + offset[a + 1], b);
    }
};

struct BlackCut
{
    uint32_t child = NONE, end = NONE, crossing = 0, maximum_ancestor = NONE, singleton_black = NONE;
};

// Store edges that leave each subtree.
struct Heaps
{
    struct Node
    {
        uint32_t left = 0, right = 0, size = 0, rank = 0, key = 0, black = NONE;
    };

    std::vector<Node> nodes;

    explicit Heaps(uint64_t upper)
    {
        need(upper < UINT32_MAX, "too many edges for 32 bit heap IDs");
        nodes.reserve(size_t(upper) + 1);
        nodes.push_back({});
    }

    uint32_t size(uint32_t n) const
    {
        return nodes[n].size;
    }

    uint32_t meld(uint32_t a, uint32_t b)
    {
        if (!a)
            return b;
        if (!b)
            return a;
        if (std::make_pair(nodes[a].key, nodes[a].black) < std::make_pair(nodes[b].key, nodes[b].black))
            std::swap(a, b);
        nodes[a].right = meld(nodes[a].right, b);
        if (nodes[nodes[a].left].rank < nodes[nodes[a].right].rank)
            std::swap(nodes[a].left, nodes[a].right);
        nodes[a].rank = nodes[nodes[a].right].rank + 1;
        uint64_t count = 1ull + size(nodes[a].left) + size(nodes[a].right);
        need(count <= UINT32_MAX, "subtree edge count exceeds 32 bits");
        nodes[a].size = uint32_t(count);
        return a;
    }

    uint32_t insert(uint32_t root, uint32_t key, uint32_t black)
    {
        need(nodes.size() < UINT32_MAX, "too many entries for 32 bit heap IDs");
        uint32_t n = uint32_t(nodes.size());
        nodes.push_back({0, 0, 1, 1, key, black});
        return meld(root, n);
    }

    uint32_t pop(uint32_t root)
    {
        need(root != 0, "cannot remove an entry from an empty heap");
        return meld(nodes[root].left, nodes[root].right);
    }
};
enum class Status : uint32_t
{
    SEPARABLE_EXACT = 0,
    BOUNDARY_POLE_LEAK = 1,
    BOUNDARY_DISCONNECTED = 2,
    SELF_ENDPOINT_UNSUPPORTED = 3
};

struct Result
{
    Status status = Status::BOUNDARY_DISCONNECTED;
    uint32_t a = 0, b = 0, printed_a = 0, printed_b = 0, component = NONE;
    bool other_inward_reached = false, outer_a_reached = false, outer_b_reached = false;
    uint64_t full_R_nodes = UINT64_MAX, selected_component_poles = 0;
    std::array<Range, 5> selected{};
    uint32_t ranges = 0;

    bool contains_tin(uint32_t t) const
    {
        for (uint32_t k = 0; k < ranges; ++k)
            if (has(selected[k], t))
                return true;
        return false;
    }
};

struct Index
{
    std::vector<uint32_t> tin, component;
    std::vector<Range> component_range;
    std::vector<BlackCut> black;
    uint64_t actual_non_tree_edges = 0, actual_visited_poles = 0;

    explicit Index(const Graph& g)
    {
        tin.assign(g.poles(), NONE);
        component.assign(g.nodes(), NONE);
        black.resize(g.nodes());
        std::vector<uint64_t> finished((uint64_t(g.poles()) + 63) / 64);
        auto done = [&](uint32_t p) { return bool((finished[p / 64] >> (p % 64)) & 1); };
        auto finish = [&](uint32_t p) { finished[p / 64] |= uint64_t(1) << (p % 64); };
        uint64_t present = 0;
        for (uint8_t p : g.present)
            present += p;
        // Reserve space for the edges outside the tree.
        Heaps heaps(g.gray_records);

        struct Frame
        {
            uint32_t pole, next_gray, heap, flags;
        };

        std::vector<Frame> stack;
        stack.reserve(size_t(2 * present));
        uint32_t clock = 0;
        for (uint32_t node = 0; node < g.nodes(); ++node) {
            if (!g.present[node] || tin[2 * node] != NONE)
                continue;
            need(component_range.size() < UINT32_MAX, "too many components for 32 bit IDs");
            uint32_t comp = uint32_t(component_range.size()), begin = clock;
            auto enter = [&](uint32_t p, bool incoming_black) {
                need(tin[p] == NONE && clock < NONE, "DFS visited a node side twice or exceeded 32 bit IDs");
                tin[p] = clock++;
                need(component[p / 2] == NONE || component[p / 2] == comp,
                     "the two sides of a node belong to different components");
                component[p / 2] = comp;
                stack.push_back({p, g.offset[p], 0, uint32_t(incoming_black)});
            };
            enter(2 * node, false);
            while (!stack.empty()) {
                Frame& f = stack.back();
                uint32_t u = f.pole, v = NONE;
                bool edge_black = false;
                if (f.next_gray < g.offset[u + 1])
                    v = g.neighbor[f.next_gray++];
                else if (!(f.flags & 2)) {
                    f.flags |= 2;
                    v = u ^ 1;
                    edge_black = true;
                } else {
                    uint32_t root = f.heap;
                    while (root && heaps.nodes[root].key >= tin[u])
                        root = heaps.pop(root);
                    if (f.flags & 1) {
                        auto& e = black[u / 2];
                        need(e.child == u, "the node edge has a different DFS child");
                        e.end = clock;
                        e.crossing = heaps.size(root);
                        if (root) {
                            e.maximum_ancestor = heaps.nodes[root].key;
                            if (e.crossing == 1)
                                e.singleton_black = heaps.nodes[root].black;
                        }
                    }
                    finish(u);
                    stack.pop_back();
                    if (!stack.empty())
                        stack.back().heap = heaps.meld(stack.back().heap, root);
                    else
                        need(root == 0, "an edge leaves the component");
                    continue;
                }
                need(v < g.poles() && g.present[v / 2], "edge refers to a missing node side");
                uint32_t parent = stack.size() > 1 ? stack[stack.size() - 2].pole : NONE;
                // Repeated links to the parent do not change the result.
                if (v == parent && edge_black == bool(f.flags & 1))
                    continue;
                if (tin[v] == NONE) {
                    if (edge_black) {
                        need(black[u / 2].child == NONE, "a node edge was added to the DFS tree twice");
                        black[u / 2].child = v;
                    }
                    enter(v, edge_black);
                    continue;
                }
                if (v == u)
                    continue;
                if (tin[v] < tin[u]) {
                    need(!done(v), "earlier node is not an active DFS ancestor");
                    f.heap = heaps.insert(f.heap, tin[v], edge_black ? u / 2 : NONE);
                } else
                    need(done(v), "DFS returned before finishing a child");
            }
            component_range.push_back({begin, clock});
        }
        actual_non_tree_edges = heaps.nodes.size() - 1;
        actual_visited_poles = clock;
        need(clock == 2 * present && actual_non_tree_edges <= g.gray_records,
             "DFS missed a node side or counted too many edges outside the tree");
        for (uint32_t node = 0; node < g.nodes(); ++node) {
            need((tin[2 * node] != NONE) == bool(g.present[node]) &&
                     (tin[2 * node + 1] != NONE) == bool(g.present[node]),
                 "DFS visited a missing node side or missed a present node side");
            if (black[node].child != NONE) {
                const auto& e = black[node];
                need(tin[e.child] < e.end && e.end <= clock &&
                         (e.crossing == 0) == (e.maximum_ancestor == NONE),
                     "the subtree range or its crossing edge count is invalid");
            }
        }
    }

    bool in_subtree(uint32_t node, uint32_t t) const
    {
        const auto& e = black[node];
        need(e.child != NONE, "node edge is not in the DFS tree");
        return tin[e.child] <= t && t < e.end;
    }

    bool full_R_contains(const Result& r, uint32_t node) const
    {
        need(node < component.size(), "requested node is outside the graph");
        if (r.status != Status::SEPARABLE_EXACT || node == r.a || node == r.b || tin[2 * node] == NONE)
            return false;
        bool a = r.contains_tin(tin[2 * node]), b = r.contains_tin(tin[2 * node + 1]);
        need(a == b, "internal node has only one side inside the bubble");
        return a;
    }

    Result query(uint32_t a, uint32_t pa, uint32_t b, uint32_t pb) const
    {
        need(a < black.size() && b < black.size() && pa < 2 && pb < 2 && tin[2 * a] != NONE &&
                 tin[2 * b] != NONE,
             "a bubble end has a missing node or an invalid sign");
        Result out;
        out.a = a;
        out.b = b;
        out.printed_a = pa;
        out.printed_b = pb;
        out.component = component[a];
        if (a == b) {
            out.status = Status::SELF_ENDPOINT_UNSUPPORTED;
            return out;
        }
        Range whole = component_range.at(component[a]);
        std::array<uint32_t, 2> removed{};
        uint32_t nt = 0;
        if (black[a].child != NONE)
            removed[nt++] = a;
        if (component[b] == component[a] && black[b].child != NONE)
            removed[nt++] = b;
        std::array<uint32_t, 6> cuts{};
        uint32_t nc = 0;
        cuts[nc++] = whole.begin;
        cuts[nc++] = whole.end;
        for (uint32_t k = 0; k < nt; ++k) {
            cuts[nc++] = tin[black[removed[k]].child];
            cuts[nc++] = black[removed[k]].end;
        }
        std::sort(cuts.begin(), cuts.begin() + nc);
        nc = uint32_t(std::unique(cuts.begin(), cuts.begin() + nc) - cuts.begin());

        struct Atom
        {
            Range range;
            uint32_t mask, group;
        };

        std::array<Atom, 5> atoms{};
        uint32_t na = 0, ng = 0;
        std::array<uint32_t, 4> groups{{NONE, NONE, NONE, NONE}}, parent{{0, 1, 2, 3}};
        auto root = [&](uint32_t v) {
            while (parent[v] != v)
                v = parent[v];
            return v;
        };
        auto join = [&](uint32_t x, uint32_t y) {
            need(groups[x] != NONE && groups[y] != NONE, "cannot join a missing tree piece");
            parent[root(groups[x])] = root(groups[y]);
        };
        for (uint32_t k = 0; k + 1 < nc; ++k) {
            uint32_t mask = 0;
            for (uint32_t j = 0; j < nt; ++j)
                if (in_subtree(removed[j], cuts[k]))
                    mask |= 1u << j;
            if (groups[mask] == NONE)
                groups[mask] = ng++;
            atoms[na++] = {{cuts[k], cuts[k + 1]}, mask, groups[mask]};
        }
        need(ng == nt + 1 && na <= 5, "wrong number of pieces after cutting two tree edges");
        if (nt == 1) {
            uint32_t tree = removed[0], back = tree == a ? b : a;
            uint32_t crossing = black[tree].crossing;
            bool deleted_back_crosses =
                in_subtree(tree, tin[2 * back]) != in_subtree(tree, tin[2 * back + 1]);
            if (deleted_back_crosses) {
                need(crossing > 0, "removed edge is missing from the crossing count");
                --crossing;
            }
            if (crossing)
                join(0, 1);
        } else if (nt == 2) {
            uint32_t u = removed[0], v = removed[1];
            if (tin[black[u].child] > tin[black[v].child])
                std::swap(u, v);
            bool nested = in_subtree(u, tin[black[v].child]);
            uint32_t cu = black[u].crossing, cv = black[v].crossing;
            uint32_t umask = removed[0] == u ? 1u : 2u, vmask = umask ^ 3u;
            if (!nested) {
                if (cu)
                    join(0, umask);
                if (cv)
                    join(0, vmask);
            } else {
                uint32_t middle = umask, inner = 3;
                if (!cu && !cv) {
                } else if (!cu)
                    join(middle, inner);
                else if (!cv)
                    join(0, middle);
                else if (cu == cv && black[v].maximum_ancestor < tin[black[u].child])
                    join(0, inner);
                else {
                    join(0, middle);
                    join(middle, inner);
                }
            }
        }
        uint32_t ia = 2 * a + (1 - pa), ib = 2 * b + (1 - pb);
        auto group_at = [&](uint32_t t) {
            for (uint32_t k = 0; k < na; ++k)
                if (has(atoms[k].range, t))
                    return atoms[k].group;
            throw std::runtime_error("requested node side is missing from the tree pieces");
        };
        uint32_t selected = root(group_at(tin[ia]));
        for (uint32_t k = 0; k < na; ++k)
            if (root(atoms[k].group) == selected) {
                Range p = atoms[k].range;
                out.selected_component_poles += uint64_t(p.end) - p.begin;
                if (out.ranges && out.selected[out.ranges - 1].end == p.begin)
                    out.selected[out.ranges - 1].end = p.end;
                else {
                    need(out.ranges < out.selected.size(),
                            "too many ranges for the component result");
                    out.selected[out.ranges++] = p;
                }
            }
        out.other_inward_reached = out.contains_tin(tin[ib]);
        out.outer_a_reached = out.contains_tin(tin[ia ^ 1]);
        out.outer_b_reached = out.contains_tin(tin[ib ^ 1]);
        if (out.outer_a_reached || out.outer_b_reached)
            out.status = Status::BOUNDARY_POLE_LEAK;
        else if (!out.other_inward_reached)
            out.status = Status::BOUNDARY_DISCONNECTED;
        else {
            need(out.selected_component_poles >= 2 && out.selected_component_poles % 2 == 0,
                 "bubble must have two ends and complete internal nodes");
            out.status = Status::SEPARABLE_EXACT;
            out.full_R_nodes = (out.selected_component_poles - 2) / 2;
        }
        return out;
    }
};
}
#endif
