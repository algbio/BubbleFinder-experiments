// Find the sizes of bubbles that are not snarls.
// Skip ultrabubbles because they are snarls.
#define main physical_compare_hidden_main
#include "physical_compare.cpp"
#undef main
#include "dominators/d_bubble_ultrabubbles.hpp"
#include <charconv>
#include <iomanip>
#include <sstream>

namespace stats {
using U64 = std::uint64_t;
constexpr U64 UNKNOWN = std::numeric_limits<U64>::max();

struct Result
{
    U64 raw = 0, certifiedUltrabubbles = 0, emptyCandidates = 0, nontrivialSnarls = 0;
    U64 separableNonminimal = 0, nonseparable = 0, nontrivial = 0, unknown = 0, witnessQueries = 0;
    std::vector<U64> sizes;
};

// Match node lengths to graph node names.
static std::vector<U64> readLengths(const std::string& path, const std::vector<std::string>& names)
{
    const paper_compare::NameIndex ids(names);
    std::vector<U64> result(names.size(), UNKNOWN);
    std::vector<uint8_t> seen(names.size(), 0);
    std::ifstream in(path, std::ios::binary);
    need(bool(in), "cannot open GFA for node lengths");
    std::string line;
    while (std::getline(in, line)) {
        if (line.size() < 2 || line[0] != 'S' || line[1] != '\t')
            continue;
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        const auto e = line.find('\t', 2);
        need(e != std::string::npos && e > 2, "malformed GFA S name");
        const auto end = line.find('\t', e + 1);
        const auto seq = std::string_view(line).substr(e + 1, end == std::string::npos ? end : end - e - 1);
        need(!seq.empty(), "empty GFA sequence field");
        const auto id = ids.find(std::string_view(line.data() + 2, e - 2));
        need(!seen[id], "duplicate GFA S record");
        seen[id] = 1;
        U64 value = seq == "*" ? UNKNOWN : static_cast<U64>(seq.size());
        U64 tagged = UNKNOWN;
        for (auto begin = end; begin != std::string::npos;) {
            ++begin;
            const auto stop = line.find('\t', begin);
            const auto field =
                std::string_view(line).substr(begin, stop == std::string::npos ? stop : stop - begin);
            if (field.substr(0, 5) == "LN:i:") {
                need(tagged == UNKNOWN, "duplicate GFA length tag");
                const auto text = field.substr(5);
                const auto conv = std::from_chars(text.data(), text.data() + text.size(), tagged);
                need(!text.empty() && conv.ec == std::errc{} && conv.ptr == text.data() + text.size() &&
                         tagged != UNKNOWN,
                     "invalid GFA length tag");
            }
            begin = stop;
        }
        if (value != UNKNOWN && tagged != UNKNOWN)
            need(value == tagged, "sequence/LN length mismatch");
        if (value == UNKNOWN)
            value = tagged;
        result[id] = value;
    }
    need(in.eof(), "error reading GFA node lengths");
    return result;
}

static bool snarlMinimal(const vg_native_split::Index& split, uint32_t x, uint32_t y,
                         const vg_native_split::Result& outer, std::vector<uint32_t>& byTime,
                         U64& witnessQueries)
{
    need(outer.status == vg_native_split::Status::SEPARABLE_EXACT,
            "snarl minimality needs a separable bubble");
    if (byTime.empty()) {
        byTime.assign(split.tin.size(), vg_native_split::NONE);
        for (uint32_t pole = 0; pole < split.tin.size(); ++pole) {
            const auto t = split.tin[pole];
            if (t != vg_native_split::NONE) {
                need(t < byTime.size() && byTime[t] == vg_native_split::NONE, "invalid split DFS order");
                byTime[t] = pole;
            }
        }
    }
    for (uint32_t r = 0; r < outer.ranges; ++r)
        for (uint32_t t = outer.selected[r].begin; t < outer.selected[r].end; ++t) {
            need(t < byTime.size() && byTime[t] != vg_native_split::NONE,
                    "DFS did not visit a node side in the split graph");
            const auto pole = byTime[t], z = pole / 2;
            if ((pole & 1u) || z == x / 2 || z == y / 2)
                continue;
            need(split.full_R_contains(outer, z),
                    "internal snarl node has sides in different components");
            for (uint32_t side = 0; side < 2; ++side) {
                ++witnessQueries;
                if (split.query(x / 2, x & 1u, z, side).status == vg_native_split::Status::SEPARABLE_EXACT &&
                    split.query(y / 2, y & 1u, z, side ^ 1u).status ==
                        vg_native_split::Status::SEPARABLE_EXACT)
                    return false;
            }
        }
    return true;
}

static Result collect(const Graph& g, const DBubbleIndex& ix, const std::vector<uint8_t>& ultrabubbleExit,
                      const std::vector<U64>& lengths, std::ostream& rows,
                      const std::vector<std::string>* names = nullptr)
{
    need(lengths.size() == g.n, "node length count differs from graph size");
    const auto nativeGraph = vg_native_split::Graph::build(std::vector<uint8_t>(g.n, 1), [&](auto visit) {
        for (const auto& e : g.edges)
            visit((2u * e.u + e.su) ^ 1u, (2u * e.v + e.sv) ^ 1u);
    });
    const vg_native_split::Index split(nativeGraph);
    const paper_compare::detail::Euler e(ix);
    Result result;
    std::vector<uint32_t> byTime;
    rows << "component\tx_state\ty_state\t";
    if (names)
        rows << "x\ty\t";
    rows << "physical_nodes\tknown_length\tunknown_nodes\treason\n";
    const U64 total = dominators::forEachDBubble(ix, [&](uint32_t c, uint32_t x, uint32_t y) {
        ++result.raw;
        if (!ultrabubbleExit.empty()) {
            const auto forward = ultrabubbleExit[y ^ 1u], reverse = ultrabubbleExit[x ^ 1u];
            need(forward == reverse, "ultrabubble result differs between directions");
            if (forward) {
                ++result.certifiedUltrabubbles;
                return;
            }
        }
        const auto body = paper_compare::detail::body(e, {c, x, y});
        if (body.members.size() <= 2) {
            ++result.emptyCandidates;
            return;
        }
        const auto native = split.query(x / 2, x & 1u, y / 2, y & 1u);
        const char* reason = "nonseparable";
        if (native.status == vg_native_split::Status::SEPARABLE_EXACT) {
            if (snarlMinimal(split, x, y, native, byTime, result.witnessQueries)) {
                ++result.nontrivialSnarls;
                return;
            }
            ++result.separableNonminimal;
            reason = "nonminimal";
        } else {
            need(native.status == vg_native_split::Status::BOUNDARY_POLE_LEAK ||
                     native.status == vg_native_split::Status::BOUNDARY_DISCONNECTED,
                 "unknown separability result for a d-bubble");
            ++result.nonseparable;
        }
        ++result.nontrivial;
        U64 sum = 0, missing = 0;
        for (auto z : body.members) {
            need(z < lengths.size(), "bubble contains a node outside the GFA graph");
            if (lengths[z] == UNKNOWN) {
                ++missing;
                continue;
            }
            need(sum <= std::numeric_limits<U64>::max() - 1 - lengths[z], "bubble length exceeds 64 bit integers");
            sum += lengths[z];
        }
        if (missing)
            ++result.unknown;
        else
            result.sizes.push_back(sum);
        rows << c << '\t' << x << '\t' << y << '\t';
        if (names) {
            std::string a = names->at(x / 2) + (x & 1u ? "-" : "+");
            std::string b = names->at(y / 2) + (y & 1u ? "-" : "+");
            if (b < a)
                std::swap(a, b);
            rows << a << '\t' << b << '\t';
        }
        rows << body.members.size() << '\t' << sum << '\t' << missing << '\t' << reason << '\n';
    });
    need(total == result.raw &&
             result.raw == result.certifiedUltrabubbles + result.emptyCandidates + result.nontrivialSnarls +
                               result.nontrivial &&
             result.nontrivial == result.separableNonminimal + result.nonseparable &&
             result.nontrivial == result.sizes.size() + result.unknown,
         "bubble size counts do not add up to the total");
    need(bool(rows), "failed writing per-bubble sizes");
    return result;
}

// Use linear interpolation to find the quartiles.
static std::string quarter(const std::vector<U64>& sizes, unsigned quartile)
{
    need(!sizes.empty() && quartile <= 4, "quartiles need sizes and a rank from 0 to 4");

    const auto rank = static_cast<__uint128_t>(sizes.size() - 1) * quartile;
    const auto index = static_cast<size_t>(rank / 4);
    const auto remainder = static_cast<unsigned>(rank % 4);
    const U64 lower = sizes[index];
    const U64 upper = sizes[std::min(index + 1, sizes.size() - 1)];
    const auto weighted = static_cast<__uint128_t>(lower) * (4 - remainder) + static_cast<__uint128_t>(upper) * remainder;
    const auto whole = static_cast<U64>(weighted / 4);
    const auto fraction = static_cast<unsigned>(weighted % 4);

    std::string result = std::to_string(whole);
    if (fraction == 1)
        result += ".25";
    else if (fraction == 2)
        result += ".5";
    else if (fraction == 3)
        result += ".75";
    return result;
}
}

#ifndef QUARTILES_NO_MAIN
int main(int argc, char** argv)
{
    try {
        need(argc == 4, "usage: quartiles GRAPH.gfa ORIGINAL_D.tsv PER_BUBBLE.tsv");
        auto bg = GFAParser::parse_file(argv[1], 1);
        ensureNames(bg);
        auto g = graphFromGFA(bg);
        dominators::DBubbleOptions opt;
        opt.bcTrees = true;
        opt.threads = 1;
        dominators::DBubbleWorkspace workspace;
        const auto ix = dominators::indexDBubbles(g, opt, &workspace);
        std::vector<uint8_t> ultrabubbleExit;
        if (ix.corridorStates == ix.source)
            ultrabubbleExit = dominators::classifyUltrabubbles(ix, workspace.offsets, workspace.edges,
                                                               workspace.dfsPre, workspace.dfsEnd);
        workspace = dominators::DBubbleWorkspace{};
        std::uint64_t count = 0;
        dominators::forEachDBubble(ix, [&](uint32_t, uint32_t, uint32_t) { ++count; });
        verifyOriginalD(argv[2], bg.node_names, ix, count);
        const auto lengths = stats::readLengths(argv[1], bg.node_names);
        std::ofstream out(argv[3], std::ios::binary);
        need(bool(out), "cannot open per-bubble output");
        auto result = stats::collect(g, ix, ultrabubbleExit, lengths, out, &bg.node_names);
        out.close();
        need(bool(out), "cannot close output");
        std::sort(result.sizes.begin(), result.sizes.end());
        std::cout << "metric\tvalue\nraw_d\t" << result.raw << "\ncertified_ultrabubbles_skipped\t"
                  << result.certifiedUltrabubbles << "\nother_trivial_candidates\t" << result.emptyCandidates
                  << "\nother_nontrivial_snarls\t" << result.nontrivialSnarls
                  << "\nseparable_nonminimal_nontrivial_d\t" << result.separableNonminimal
                  << "\nnonseparable_nontrivial_d\t" << result.nonseparable
                  << "\nminimality_witness_queries\t" << result.witnessQueries << "\nnonsnarl_nontrivial_d\t"
                  << result.nontrivial << "\ncomplete_length_d\t" << result.sizes.size()
                  << "\nunknown_length_d\t" << result.unknown << "\nphysical_nodes\t" << g.n
                  << "\nsource_reachable_states\t" << ix.reachableStates << "\ncorridor_states\t"
                  << ix.corridorStates << '\n';
        if (!result.sizes.empty())
            for (unsigned p = 1; p <= 4; ++p)
                std::cout << "Q" << p << "_bp\t" << stats::quarter(result.sizes, p) << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "non-snarl quartiles failed: " << e.what() << '\n';
        return 1;
    }
}
#endif
