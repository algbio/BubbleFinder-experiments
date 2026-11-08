// Compare the nontrivial bubbles found by BubbleFinder and vg.
#include "io/gfa_parser.hpp"
#include "dominators/d_bubbles.hpp"
#include "analysis/body.hpp"
#include "analysis/owners.hpp"
#include "analysis/forest.hpp"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

using dominators::DBubbleIndex;
using dominators::Graph;
using paper_body_native::Hierarchy;
using paper_body_native::Bubble;
namespace core = dbubble::full_static_v1;

static void need(bool ok, const std::string& why)
{
    if (!ok)
        throw std::runtime_error(why);
}

static std::vector<std::uint64_t> physicalSizes(const DBubbleIndex& ix, const Hierarchy& h)
{
    auto owner = d_bubble_owners::build(h, ix.parent, ix.component);
    const std::size_t n = h.bubbles.size();
    need(owner.owner1.size() == ix.component.size() && owner.owner2.size() == ix.component.size(),
         "node assignment list has the wrong size");
    std::vector<core::Index> parent(n, core::NONE);
    for (std::size_t i = 0; i < n; ++i)
        if (h.physicalParent[i] != paper_body_native::NONE)
            parent[i] = h.physicalParent[i];
    const core::detail::Forest forest(parent);
    std::vector<std::int64_t> delta(n, 0);
    for (std::size_t z = 0; z < owner.owner1.size(); ++z) {
        const auto a = owner.owner1[z], b = owner.owner2[z];
        need(a == core::NONE || a < n, "first containing bubble is outside the list");
        need(b == core::NONE || (a != core::NONE && b < n && a != b),
                "second containing bubble is outside the list");
        if (a != core::NONE)
            ++delta[a];
        if (b != core::NONE) {
            ++delta[b];
            const auto lca = forest.lca(a, b);
            if (lca != core::NONE)
                --delta[lca];
        }
    }
    std::vector<std::uint64_t> size(n);
    for (auto it = forest.order.rbegin(); it != forest.order.rend(); ++it) {
        const auto i = *it;
        need(delta[i] >= 2 && static_cast<std::uint64_t>(delta[i]) <= ix.component.size(),
             "bubble must contain at least two nodes");
        size[i] = static_cast<std::uint64_t>(delta[i]);
        if (parent[i] != core::NONE)
            delta[parent[i]] += delta[i];
    }
    // Check the sizes directly on small graphs.
    if (ix.component.size() <= 5000 && n <= 10000) {
        const paper_compare::detail::Euler e(ix);
        for (std::size_t i = 0; i < n; ++i) {
            const auto& p = h.bubbles[i];
            const auto direct = paper_compare::detail::body(e, {p.component, p.x, p.y});
            need(size[i] == direct.members.size(),
                    "assigned node count differs from the direct bubble count");
        }
    }
    return size;
}

static void ensureNames(BiGraph& bg)
{
    if (bg.node_names.size() == bg.n_nodes)
        return;
    need(bg.numeric_node_names.size() == bg.n_nodes && bg.numeric_node_name_valid.size() == bg.n_nodes,
         "GFA parser did not retain names");
    bg.node_names.resize(bg.n_nodes);
    std::size_t j = 0;
    for (std::uint32_t i = 0; i < bg.n_nodes; ++i) {
        if (bg.numeric_node_name_valid[i])
            bg.node_names[i] = std::to_string(bg.numeric_node_names[i]);
        else {
            while (j < bg.string_node_names.size() && bg.string_node_names[j].first < i)
                ++j;
            need(j < bg.string_node_names.size() && bg.string_node_names[j].first == i,
                 "missing GFA segment name");
            bg.node_names[i] = bg.string_node_names[j].second;
        }
    }
    std::vector<std::uint64_t>().swap(bg.numeric_node_names);
    std::vector<std::uint8_t>().swap(bg.numeric_node_name_valid);
    std::vector<std::pair<std::uint32_t, std::string>>().swap(bg.string_node_names);
}

static Graph graphFromGFA(BiGraph& bg)
{
    Graph g;
    g.n = bg.n_nodes;
    g.edges.reserve(bg.links.size());
    for (const auto& l : bg.links) {
        need((l.orient_src == '+' || l.orient_src == '-') && (l.orient_dst == '+' || l.orient_dst == '-'),
             "invalid GFA orientation");
        dominators::BiEdge e{l.src, l.dst, static_cast<std::uint8_t>(l.orient_src == '-'),
                             static_cast<std::uint8_t>(l.orient_dst == '+')};
        if (e.u > e.v || (e.u == e.v && e.su > e.sv)) {
            std::swap(e.u, e.v);
            std::swap(e.su, e.sv);
        }
        g.edges.push_back(e);
    }
    std::vector<BiLink>().swap(bg.links);
    auto key = [](const auto& e) { return std::make_tuple(e.u, e.v, e.su, e.sv); };
    std::sort(g.edges.begin(), g.edges.end(), [&](const auto& a, const auto& b) { return key(a) < key(b); });
    g.edges.erase(std::unique(g.edges.begin(), g.edges.end(),
                              [&](const auto& a, const auto& b) { return key(a) == key(b); }),
                  g.edges.end());
    return g;
}

static void verifyOriginalD(const std::string& path, const std::vector<std::string>& names,
                            const DBubbleIndex& ix, std::uint64_t expected)
{
    const paper_compare::NameIndex index(names);
    std::ifstream f(path);
    need(bool(f), "cannot open original D TSV");
    std::vector<std::uint8_t> seen((static_cast<std::uint64_t>(ix.source) + 7) / 8, 0);
    std::string line;
    bool header = false, standard = false;
    std::uint64_t n = 0;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#')
            continue;
        if (!header) {
            standard = line != "component\tx\ty";
            if (standard) {
                need(line.find_first_not_of("0123456789") == std::string::npos && !line.empty(),
                     "unexpected original D header");
                need(std::stoull(line) == expected, "original D header count differs");
            }
            header = true;
            continue;
        }
        std::string xs, ys;
        if (standard) {
            const auto separator = line.find(' ');
            need(separator != std::string::npos && line.find(' ', separator + 1) == std::string::npos,
                 "bad original D row");
            xs = line.substr(0, separator);
            ys = line.substr(separator + 1);
        } else {
            const auto a = line.find('\t'), b = line.find('\t', a + 1);
            need(a != std::string::npos && b != std::string::npos &&
                     line.find('\t', b + 1) == std::string::npos,
                 "bad original D row");
            xs = line.substr(a + 1, b - a - 1);
            ys = line.substr(b + 1);
        }
        need(paper_compare::validPole(xs) && paper_compare::validPole(ys),
                "d-bubble end needs a node name and sign");
        const auto state = [&](const std::string& s) {
            return 2u * index.find(std::string_view(s.data(), s.size() - 1)) +
                   static_cast<std::uint32_t>(s.back() == '-');
        };
        auto x = state(xs), y = state(ys);
        if (x > y)
            std::swap(x, y);
        need(x / 2 != y / 2 && ix.parent[y ^ 1u] == x && ix.parent[x ^ 1u] == y,
             "input d-bubble fails the dominator check");
        need(!(seen[x / 8] & (1u << (x % 8))), "d-bubble input repeats a bubble");
        seen[x / 8] |= static_cast<std::uint8_t>(1u << (x % 8));
        ++n;
    }
    need(f.eof() && header && n == expected,
            "d-bubble rows do not match the header count");
}

struct Summary
{
    std::uint64_t d = 0, vg = 0, both = 0, dOnly = 0, vgOnly = 0, disagreements = 0;
};

static void writeBubble(std::ostream* out, const std::vector<std::string>& names, std::uint32_t x,
                      std::uint32_t y)
{
    if (!out)
        return;
    std::string a = names.at(x / 2) + (x & 1u ? "-" : "+");
    std::string b = names.at(y / 2) + (y & 1u ? "-" : "+");
    if (b < a)
        std::swap(a, b);
    *out << a << '\t' << b << '\n';
    need(bool(*out), "cannot write the bubble file");
}

// Check that the bubbles drawn in S1 lie inside it.
static void checkS1Containment(const DBubbleIndex& ix, const paper_compare::Catalogue& cat,
                               const vg_native_split::Index& native, const std::vector<std::string>& names,
                               std::ostream& out)
{
    const paper_compare::NameIndex ids(names);
    const auto state = [&](const std::string& pole) {
        need(paper_compare::validPole(pole), "invalid selected hierarchy boundary");
        return 2u * ids.find(std::string_view(pole.data(), pole.size() - 1)) +
               static_cast<std::uint32_t>(pole.back() == '-');
    };
    auto sx = state("226327717+"), sy = state("226327734-");
    if (sx > sy)
        std::swap(sx, sy);
    const auto found = std::find_if(cat.extra.begin(), cat.extra.end(),
                                    [&](const auto& p) { return p.x == sx && p.y == sy; });
    need(found != cat.extra.end(), "S1 is not an imported vg-only snarl");
    const auto s1 = native.query(sx / 2, sx & 1u, sy / 2, sy & 1u);
    need(s1.status == vg_native_split::Status::SEPARABLE_EXACT, "S1 is not separable");
    const auto s1Nodes = s1.full_R_nodes + 2;
    need(s1Nodes == 22, "S1 physical body size differs from the displayed region");
    const paper_compare::detail::Euler euler(ix);
    const std::vector<std::tuple<const char*, const char*, const char*>> selected = {
        {"D2", "226327717+", "226327720-"},  {"S1a", "226327720+", "226327723-"},
        {"S1b", "226327723+", "226327726-"}, {"S1c", "226327726+", "226327728-"},
        {"S1d", "226327728+", "226327731-"}, {"D3", "226327731+", "226327734-"},
    };
    out << "metric\tvalue\nS1_physical_nodes\t" << s1Nodes << '\n';
    for (const auto& item : selected) {
        const auto x = state(std::get<1>(item)), y = state(std::get<2>(item));
        need(ix.parent[y ^ 1u] == x && ix.parent[x ^ 1u] == y, "A displayed S1 child is not a d-bubble");
        const auto body = paper_compare::detail::body(euler, {ix.component[x / 2], x, y});
        need(body.members.size() < s1Nodes, "S1 child is not a strict subregion");
        need(std::all_of(body.members.begin(), body.members.end(),
                         [&](std::uint32_t u) { return paper_compare::detail::member(native, s1, u); }),
             "A displayed child is not physically contained in S1");
        if (std::string(std::get<0>(item)) == "D2" || std::string(std::get<0>(item)) == "D3")
            need(body.members.size() == 4, "D2 or D3 does not have the displayed four-node body");
        out << std::get<0>(item) << "_physical_nodes\t" << body.members.size() << '\n';
        out << std::get<0>(item) << "_strictly_inside_S1\t1\n";
    }
    need(bool(out), "cannot write S1 containment report");
}

static Summary compare(const Graph& g, const DBubbleIndex& ix, const Hierarchy& h,
                       const std::vector<std::uint64_t>& sizes, const paper_compare::Catalogue& cat,
                       const std::vector<std::string>& names, std::ostream* dOut, std::ostream* vgOut,
                       std::ostream* hierarchyOut)
{
    need(h.bubbles.size() == sizes.size(), "the bubble list and size list have different lengths");
    auto nativeGraph = vg_native_split::Graph::build(std::vector<std::uint8_t>(g.n, 1), [&](auto visit) {
        for (const auto& e : g.edges)
            visit((2u * e.u + e.su) ^ 1u, (2u * e.v + e.sv) ^ 1u);
    });
    const vg_native_split::Index native(nativeGraph);
    Summary s;
    std::uint64_t commonSeen = 0;
    const auto hasInside = [&](const paper_compare::Bubble& p) {
        const auto result = native.query(p.x / 2, p.x & 1u, p.y / 2, p.y & 1u);
        need(result.status == vg_native_split::Status::SEPARABLE_EXACT,
             "vg bubble is not separable at its ends");
        return result.full_R_nodes > 0;
    };
    for (std::size_t i = 0; i < h.bubbles.size(); ++i) {
        const auto& p = h.bubbles[i];
        const bool d = sizes[i] > 2;
        const bool vgPresent = cat.common(p.x);
        need(vgPresent == cat.common(p.y), "vg match differs between the two bubble ends");
        bool vg = false;
        if (vgPresent) {
            ++commonSeen;
            vg = hasInside({p.component, p.x, p.y});
            if (vg != d)
                ++s.disagreements;
        }
        if (d)
            writeBubble(dOut, names, p.x, p.y);
        if (vg)
            writeBubble(vgOut, names, p.x, p.y);
        s.d += d;
        s.vg += vg;
        s.both += (d && vg);
        s.dOnly += (d && !vg);
        s.vgOnly += (vg && !d);
    }
    need(commonSeen == cat.commonD, "shared bubble count differs from the vg input");
    for (const auto& p : cat.extra)
        if (hasInside(p)) {
            ++s.vg;
            ++s.vgOnly;
            writeBubble(vgOut, names, p.x, p.y);
        }
    need(s.d == s.both + s.dOnly && s.vg == s.both + s.vgOnly,
            "shared and unshared counts do not add up");
    if (hierarchyOut)
        checkS1Containment(ix, cat, native, names, *hierarchyOut);
    return s;
}

int main(int argc, char** argv)
{
    try {
        need(
            argc == 4 || argc == 6 || argc == 7,
            "usage: physical_compare GRAPH.gfa ORIGINAL_D.tsv NORMALIZED_VG.tsv [D_NONTRIVIAL VG_NONTRIVIAL [S1_CONTAINMENT]]");
        auto bg = GFAParser::parse_file(argv[1], 1);
        ensureNames(bg);
        auto g = graphFromGFA(bg);
        dominators::DBubbleOptions opt;
        opt.bcTrees = true;
        opt.threads = 1;
        const auto ix = dominators::indexDBubbles(g, opt);
        std::vector<Bubble> bubbles;
        const auto total = dominators::forEachDBubble(
            ix, [&](std::uint32_t c, std::uint32_t x, std::uint32_t y) { bubbles.push_back({c, x, y}); });
        need(total == bubbles.size(), "d-bubble count differs from the bubble list");
        verifyOriginalD(argv[2], bg.node_names, ix, total);
        const auto h = paper_body_native::build(ix.source, ix.reachableStates, ix.parent, ix.component,
                                                std::move(bubbles));
        const auto sizes = physicalSizes(ix, h);
        const auto cat = paper_compare::readCatalogue(argv[3], bg.node_names, ix);
        std::ofstream dOut, vgOut, hierarchyOut;
        if (argc >= 6) {
            dOut.open(argv[4], std::ios::binary);
            vgOut.open(argv[5], std::ios::binary);
            need(bool(dOut) && bool(vgOut), "cannot open physical bubble outputs");
        }
        if (argc == 7) {
            hierarchyOut.open(argv[6], std::ios::binary);
            need(bool(hierarchyOut), "cannot open S1 containment output");
        }
        const auto out = compare(g, ix, h, sizes, cat, bg.node_names, argc >= 6 ? &dOut : nullptr,
                                 argc >= 6 ? &vgOut : nullptr, argc == 7 ? &hierarchyOut : nullptr);
        std::cout << "metric\tvalue\nraw_d\t" << total << "\nraw_vg\t" << cat.rows << "\nraw_common\t"
                  << cat.commonD << "\nnontrivial_d\t" << out.d << "\nnontrivial_vg\t" << out.vg
                  << "\nnontrivial_common\t" << out.both << "\nnontrivial_d_only\t" << out.dOnly
                  << "\nnontrivial_vg_only\t" << out.vgOnly << "\ncommon_body_emptiness_disagreements\t"
                  << out.disagreements << "\nphysical_nodes\t" << g.n << "\nlinks_unique\t" << g.edges.size()
                  << "\nsource_reachable_states\t" << ix.reachableStates << "\ncorridor_states\t"
                  << ix.corridorStates << "\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "physical comparison failed: " << e.what() << '\n';
        return 1;
    }
}
