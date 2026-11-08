#pragma once

#include "dominators/d_bubble_hierarchy.hpp"
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Find the bubbles that contain each node.
namespace d_bubble_owners {
constexpr uint32_t U32_NONE = std::numeric_limits<uint32_t>::max();
constexpr size_t NONE = std::numeric_limits<size_t>::max();

inline void require(bool ok, const char* why)
{
    if (!ok)
        throw std::runtime_error(std::string("bubble nodes: ") + why);
}

struct Owners
{
    std::vector<size_t> owner1, owner2;
};

namespace detail {
struct SourcePoints
{
    std::vector<uint32_t> parent, owner;
    uint64_t reciprocalEntries = 0;
};

inline SourcePoints sourcePoints(const paper_body_native::Hierarchy& h, const std::vector<uint32_t>& parent,
                                 const std::vector<uint32_t>& component)
{
    const uint32_t source = h.source;
    require(source > 0 && source < U32_NONE && !(source & 1u), "source ID must be positive and even");
    require(parent.size() == static_cast<size_t>(source) + 1, "parent list has the wrong size");
    require(parent[source] == U32_NONE, "added source must have no parent");
    require(component.size() * 2ull == source, "component list has the wrong size");
    require(h.reachableStates <= source, "reachable node count exceeds graph size");
    require(h.bubbles.size() <= (U32_NONE - 1u) / 2u, "too many bubbles for 32 bit IDs");
    require(h.physicalParent.size() == h.bubbles.size(), "bubble parent list has the wrong size");

    const uint32_t m = static_cast<uint32_t>(2 * h.bubbles.size());
    SourcePoints result;
    result.parent.assign(m, U32_NONE);
    result.owner.assign(source, U32_NONE);
    std::vector<uint32_t> first(parent.size(), U32_NONE), next(parent.size(), U32_NONE);
    std::vector<uint32_t> event(parent.size(), U32_NONE);

    uint64_t defined = 0;
    for (uint32_t q = 0; q < source; ++q) {
        const uint32_t p = parent[q];
        if (p == U32_NONE)
            continue;
        require(p <= source, "tree parent is outside the graph");
        require(p != q, "node cannot be its own tree parent");
        next[q] = first[p];
        first[p] = q;
        ++defined;
    }
    require(defined == h.reachableStates, "tree parent count differs from the reachable node count");
    for (uint32_t i = 0; i < h.bubbles.size(); ++i) {
        const auto& p = h.bubbles[i];
        require(p.x < p.y && p.y < source && p.x / 2 != p.y / 2 && component[p.x / 2] == p.component &&
                    component[p.y / 2] == p.component && parent[p.y ^ 1u] == p.x && parent[p.x ^ 1u] == p.y,
                "bubble ends do not match their components or immediate dominators");
        require(event[p.x] == U32_NONE && event[p.y] == U32_NONE, "two d-bubbles use the same signed entry");
        event[p.x] = 2 * i;
        event[p.y] = 2 * i + 1;
    }

    for (uint32_t q = 0; q < source; ++q) {
        const uint32_t r = parent[q ^ 1u];
        const bool reciprocal =
            r < source && q / 2 != r / 2 && component[r / 2] == component[q / 2] && parent[r ^ 1u] == q;
        if (!reciprocal) {
            require(event[q] == U32_NONE, "listed bubble fails the dominator check");
            continue;
        }
        require(event[q] < m, "a d-bubble is missing from the bubble list");
        const auto& p = h.bubbles[event[q] / 2];
        require((p.x == q && p.y == r) || (p.x == r && p.y == q),
                "signed entry refers to a different bubble");
        ++result.reciprocalEntries;
    }
    require(result.reciprocalEntries == m, "signed entry count differs from bubble count");

    const auto exitOf = [&](uint32_t o) { return paper_body_native::exit(h.bubbles[o / 2], o & 1u); };

    uint32_t active = U32_NONE, u = source;
    uint64_t visited = 0, occurrences = 0;
    bool entering = true;
    while (true) {
        if (entering) {
            require(++visited <= h.reachableStates + 1, "source tree walk visited too many nodes");
            const uint32_t e = event[u];
            if (e != U32_NONE) {
                result.parent[e] = active;
                active = e;
                ++occurrences;
            }
            // Record the current bubble before visiting its exit.
            if (u < source)
                result.owner[u] = active;
            if (first[u] != U32_NONE) {
                const uint32_t child = first[u];
                if (e != U32_NONE && child == exitOf(e))
                    active = result.parent[e];
                u = child;
                continue;
            }
        }
        const uint32_t e = event[u];
        if (e != U32_NONE)
            active = result.parent[e];
        if (u == source)
            break;
        const uint32_t p = parent[u], pe = event[p];
        if (pe != U32_NONE && u == exitOf(pe))
            active = pe;
        if (next[u] != U32_NONE) {
            const uint32_t child = next[u];
            if (pe != U32_NONE && child == exitOf(pe))
                active = result.parent[pe];
            u = child;
            entering = true;
        } else {
            u = p;
            entering = false;
        }
    }
    require(visited == h.reachableStates + 1, "source tree walk missed a node");
    require(occurrences == m, "source tree walk missed a bubble direction");
    require(active == U32_NONE, "bubble remains active after the tree walk");
    for (uint32_t o = 0; o < m; ++o) {
        const uint32_t p = result.parent[o];
        if (p == U32_NONE)
            continue;
        require(p < m, "source parent is outside the bubble list");
        require(p != o, "bubble cannot be its own source parent");
        require(h.bubbles[p / 2].component == h.bubbles[o / 2].component,
                "source parent belongs to another component");
    }
    return result;
}

// Track the parents of the bubble regions.
struct PhysicalEuler
{
    uint32_t root;
    std::vector<uint32_t> tin, end;

    explicit PhysicalEuler(const paper_body_native::Hierarchy& h)
        : root(static_cast<uint32_t>(h.bubbles.size())), tin(h.bubbles.size() + 1, U32_NONE),
          end(h.bubbles.size() + 1, U32_NONE)
    {
        require(h.bubbles.size() < U32_NONE, "too many bubbles for 32 bit IDs");
        require(h.physicalParent.size() == h.bubbles.size(), "bubble parent list has the wrong size");
        std::vector<uint32_t> first(h.bubbles.size() + 1, U32_NONE), next(h.bubbles.size(), U32_NONE);
        for (uint32_t i = 0; i < root; ++i) {
            const uint32_t p = h.physicalParent[i];
            if (p != U32_NONE) {
                require(p < root, "parent is outside the bubble list");
                require(p != i, "bubble cannot be its own parent");
                require(h.bubbles[p].component == h.bubbles[i].component,
                        "parent belongs to another component");
            }
            const uint32_t parent = p == U32_NONE ? root : p;
            next[i] = first[parent];
            first[parent] = i;
        }

        uint32_t u = root, clock = 0;
        bool entering = true;
        while (true) {
            if (entering) {
                require(tin[u] == U32_NONE && clock <= root,
                        "hierarchy walk visited a bubble twice or exceeded the bubble count");
                tin[u] = clock++;
                if (first[u] != U32_NONE) {
                    u = first[u];
                    continue;
                }
            }
            end[u] = clock;
            if (u == root)
                break;
            if (next[u] != U32_NONE) {
                u = next[u];
                entering = true;
            } else {
                u = h.physicalParent[u] == U32_NONE ? root : h.physicalParent[u];
                entering = false;
            }
        }
        require(clock == static_cast<uint64_t>(root) + 1,
                "hierarchy walk missed a bubble");
    }

    bool ancestor(uint32_t a, uint32_t b) const
    {
        require(a <= root && b <= root, "requested bubble is outside the hierarchy");
        return tin[a] <= tin[b] && tin[b] < end[a];
    }

    uint32_t deepest(uint32_t a, uint32_t b) const
    {
        if (a == U32_NONE)
            return b;
        if (b == U32_NONE)
            return a;
        require(ancestor(a, b) || ancestor(b, a), "overlapping bubbles are not nested");
        return ancestor(a, b) ? b : a;
    }
};

inline std::vector<uint32_t> orientedPoints(const SourcePoints& points, uint64_t& queries)
{
    const uint32_t m = static_cast<uint32_t>(points.parent.size()), root = m;
    require(!(m & 1u) && !(points.owner.size() & 1u), "each node and bubble needs two directions");
    require(m < U32_NONE && points.owner.size() < U32_NONE, "node or bubble count exceeds 32 bit IDs");
    std::vector<uint32_t> c(m, U32_NONE), afirst(static_cast<size_t>(m) + 1, U32_NONE), anext(m, U32_NONE);
    std::vector<uint32_t> first(static_cast<size_t>(m) + 1, U32_NONE), next(m, U32_NONE);
    for (uint32_t u = 0; u < m; ++u) {
        c[u] = points.parent[u ^ 1u] == U32_NONE ? U32_NONE : points.parent[u ^ 1u] ^ 1u;
        const uint32_t ap = points.parent[u] == U32_NONE ? root : points.parent[u];
        const uint32_t cp = c[u] == U32_NONE ? root : c[u];
        require(ap <= root && cp <= root, "parent is outside the bubble list");
        require(ap != u && cp != u, "bubble cannot be its own parent");
        anext[u] = afirst[ap];
        afirst[ap] = u;
        next[u] = first[cp];
        first[cp] = u;
    }

    std::vector<uint32_t> depth(static_cast<size_t>(m) + 1, 0), subtree(static_cast<size_t>(m) + 1, 1);
    std::vector<uint32_t> heavy(static_cast<size_t>(m) + 1, U32_NONE), order;
    order.reserve(static_cast<size_t>(m) + 1);
    order.push_back(root);
    for (size_t i = 0; i < order.size(); ++i) {
        const uint32_t u = order[i];
        for (uint32_t v = first[u]; v != U32_NONE; v = next[v]) {
            require(order.size() <= m, "target hierarchy contains a cycle");
            depth[v] = depth[u] + 1;
            order.push_back(v);
        }
    }
    require(order.size() == static_cast<size_t>(m) + 1,
            "target hierarchy walk missed a bubble");
    for (size_t i = order.size(); i-- > 0;) {
        const uint32_t u = order[i];
        for (uint32_t v = first[u]; v != U32_NONE; v = next[v]) {
            require(static_cast<uint64_t>(subtree[u]) + subtree[v] <= static_cast<uint64_t>(m) + 1,
                    "target subtree size exceeds the number of bubbles");
            subtree[u] += subtree[v];
            if (heavy[u] == U32_NONE || subtree[v] > subtree[heavy[u]])
                heavy[u] = v;
        }
    }

    std::vector<uint32_t> head(static_cast<size_t>(m) + 1, U32_NONE),
        pos(static_cast<size_t>(m) + 1, U32_NONE);
    order.clear();
    order.push_back(root);
    uint32_t clock = 0;
    while (!order.empty()) {
        const uint32_t chain = order.back();
        order.pop_back();
        for (uint32_t u = chain; u != U32_NONE; u = heavy[u]) {
            head[u] = chain;
            pos[u] = clock++;
            for (uint32_t v = first[u]; v != U32_NONE; v = next[v])
                if (v != heavy[u])
                    order.push_back(v);
        }
    }
    require(clock == static_cast<uint64_t>(m) + 1, "tree indexing missed a bubble");
    std::vector<uint32_t>().swap(first);
    std::vector<uint32_t>().swap(next);
    std::vector<uint32_t>().swap(subtree);
    std::vector<uint32_t>().swap(heavy);
    std::vector<uint32_t>().swap(order);

    size_t base = 1;
    while (base < static_cast<size_t>(m) + 1) {
        require(base <= std::vector<uint32_t>().max_size() / 2, "too many bubbles for the tree index");
        base *= 2;
    }
    require(base <= std::vector<uint32_t>().max_size() / 2, "too many bubbles for the tree index");
    std::vector<uint32_t> tree(2 * base, U32_NONE);
    const auto best = [&](uint32_t a, uint32_t b) {
        if (a == U32_NONE)
            return b;
        if (b == U32_NONE)
            return a;
        return depth[a] > depth[b] || (depth[a] == depth[b] && a < b) ? a : b;
    };
    const auto mark = [&](uint32_t u, bool on) {
        size_t p = base + pos[u];
        tree[p] = on ? u : U32_NONE;
        while (p > 1) {
            p /= 2;
            tree[p] = best(tree[2 * p], tree[2 * p + 1]);
        }
    };
    const auto rangeMax = [&](size_t l, size_t r) {
        uint32_t answer = U32_NONE;
        l += base;
        r += base;
        while (l < r) {
            if (l & 1u)
                answer = best(answer, tree[l++]);
            if (r & 1u)
                answer = best(answer, tree[--r]);
            l /= 2;
            r /= 2;
        }
        return answer;
    };
    const auto nearest = [&](uint32_t u) {
        uint32_t answer = U32_NONE;
        while (true) {
            const uint32_t chain = head[u];
            answer = best(answer, rangeMax(pos[chain], static_cast<size_t>(pos[u]) + 1));
            if (chain == root)
                break;
            u = c[chain] == U32_NONE ? root : c[chain];
        }
        return answer;
    };
    std::vector<uint32_t> pointFirst(static_cast<size_t>(m) + 1, U32_NONE),
        pointNext(points.owner.size(), U32_NONE);
    std::vector<uint32_t> result(points.owner.size(), U32_NONE);
    for (uint32_t q = 0; q < points.owner.size(); ++q) {
        const uint32_t a = points.owner[q] == U32_NONE ? root : points.owner[q];
        require(a <= root, "node refers to a missing source bubble");
        pointNext[q] = pointFirst[a];
        pointFirst[a] = q;
    }
    uint32_t u = root;
    uint64_t visited = 0;
    bool entering = true;
    while (true) {
        if (entering) {
            require(++visited <= static_cast<uint64_t>(m) + 1, "source hierarchy contains a cycle");
            if (u != root)
                mark(u, true);
            for (uint32_t q = pointFirst[u]; q != U32_NONE; q = pointNext[q]) {
                const uint32_t aTwin = points.owner[q ^ 1u];
                const uint32_t targetOwner = aTwin == U32_NONE ? root : aTwin ^ 1u;
                result[q] = nearest(targetOwner);
                ++queries;
            }
            if (afirst[u] != U32_NONE) {
                u = afirst[u];
                continue;
            }
        }
        if (u == root)
            break;
        mark(u, false);
        if (anext[u] != U32_NONE) {
            u = anext[u];
            entering = true;
        } else {
            u = points.parent[u] == U32_NONE ? root : points.parent[u];
            entering = false;
        }
    }
    require(visited == static_cast<uint64_t>(m) + 1, "source hierarchy walk missed a bubble");
    require(tree[1] == U32_NONE, "bubble remains marked after the hierarchy walk");
    require(queries == points.owner.size(), "containing bubble search missed a node direction");
    for (uint32_t q = 0; q < result.size(); ++q)
        require(result[q ^ 1u] == (result[q] == U32_NONE ? U32_NONE : result[q] ^ 1u),
                "containing bubble differs between node directions");
    return result;
}
}

inline Owners build(const paper_body_native::Hierarchy& h, const std::vector<uint32_t>& sourceParent,
                    const std::vector<uint32_t>& component)
{
    auto points = detail::sourcePoints(h, sourceParent, component);
    const detail::PhysicalEuler physical(h);
    Owners result;
    uint64_t queries = 0;
    auto oriented = detail::orientedPoints(points, queries);
    result.owner1.assign(component.size(), NONE);
    result.owner2.assign(component.size(), NONE);
    std::vector<std::array<uint32_t, 2>> boundary(component.size(),
                                                  std::array<uint32_t, 2>{{U32_NONE, U32_NONE}});
    for (uint32_t i = 0; i < h.bubbles.size(); ++i) {
        for (uint32_t z : {h.bubbles[i].x / 2, h.bubbles[i].y / 2}) {
            auto& b = boundary[z];
            require(b[0] != i && b[1] != i, "bubble is repeated in a node end list");
            require(b[1] == U32_NONE, "node is an end of more than two bubbles");
            if (b[0] == U32_NONE)
                b[0] = i;
            else
                b[1] = i;
        }
    }
    const auto isEndpoint = [&](uint32_t i, uint32_t z) {
        return h.bubbles[i].x / 2 == z || h.bubbles[i].y / 2 == z;
    };
    for (uint32_t z = 0; z < component.size(); ++z) {
        uint32_t internal = U32_NONE;
        for (uint32_t q : {2 * z, 2 * z + 1}) {
            uint32_t candidate = oriented[q] == U32_NONE ? U32_NONE : oriented[q] / 2;
            unsigned skipped = 0;
            while (candidate != U32_NONE && isEndpoint(candidate, z)) {
                require(++skipped <= 2,
                        "node is an end of more than two bubbles");
                candidate = h.physicalParent[candidate];
            }
            internal = physical.deepest(internal, candidate);
        }
        if (internal != U32_NONE) {
            require(!isEndpoint(internal, z) && h.bubbles[internal].component == component[z],
                    "node is not inside its assigned bubble");
        }
        const std::array<uint32_t, 3> candidates{{internal, boundary[z][0], boundary[z][1]}};
        std::array<uint32_t, 2> maximal{{U32_NONE, U32_NONE}};
        unsigned count = 0;
        for (size_t j = 0; j < candidates.size(); ++j) {
            const uint32_t c = candidates[j];
            if (c == U32_NONE)
                continue;
            bool redundant = false;
            for (size_t k = 0; k < candidates.size(); ++k) {
                const uint32_t d = candidates[k];
                if (d == U32_NONE || j == k)
                    continue;
                if ((c == d && k < j) || (c != d && physical.ancestor(c, d)))
                    redundant = true;
            }
            if (redundant)
                continue;
            require(count < 2, "node belongs to more than two outermost bubbles");
            maximal[count++] = c;
        }
        if (count == 2) {
            require(!physical.ancestor(maximal[0], maximal[1]) && !physical.ancestor(maximal[1], maximal[0]),
                    "outermost bubbles must not contain each other");
            if (maximal[1] < maximal[0])
                std::swap(maximal[0], maximal[1]);
        }
        if (count)
            result.owner1[z] = maximal[0];
        if (count == 2)
            result.owner2[z] = maximal[1];
    }
    return result;
}
}
