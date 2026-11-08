// Find the nontrivial bubbles reported by Billi.
#define QUARTILES_NO_MAIN
#include "quartiles.cpp"

int main(int argc, char** argv)
{
    try {
        need(argc == 6, "usage: paper_billi_filter GRAPH.gfa BILLI_BUBBLES VG_NONTRIV OUTPUT OUTSIDE_VG");
        auto bg = GFAParser::parse_file(argv[1], 1);
        ensureNames(bg);
        auto g = graphFromGFA(bg);
        const paper_compare::NameIndex ids(bg.node_names);
        const auto splitGraph =
            vg_native_split::Graph::build(std::vector<std::uint8_t>(g.n, 1), [&](auto visit) {
                for (const auto& e : g.edges)
                    visit((2u * e.u + e.su) ^ 1u, (2u * e.v + e.sv) ^ 1u);
            });
        const vg_native_split::Index split(splitGraph);
        std::ifstream in(argv[2]);
        std::ifstream vg(argv[3]);
        std::ofstream out(argv[4]), outside(argv[5]);
        need(bool(in) && bool(vg) && bool(out) && bool(outside), "cannot open Billi bubble files");
        std::string line, vgline;
        bool vgReady = static_cast<bool>(std::getline(vg, vgline));
        std::vector<std::uint32_t> byTime;
        std::uint64_t total = 0, nontrivial = 0, missed = 0, witnessQueries = 0;
        outside << "x\ty\tsnarl\n";
        while (std::getline(in, line)) {
            if (line.empty())
                continue;
            const auto tab = line.find('\t');
            need(tab != std::string::npos && line.find('\t', tab + 1) == std::string::npos,
                 "invalid Billi bubble row");
            const std::string a = line.substr(0, tab), b = line.substr(tab + 1);
            need(paper_compare::validPole(a) && paper_compare::validPole(b) && a < b,
                 "invalid Billi signed poles");
            const auto x =
                2u * ids.find(std::string_view(a.data(), a.size() - 1)) + std::uint32_t(a.back() == '-');
            const auto y =
                2u * ids.find(std::string_view(b.data(), b.size() - 1)) + std::uint32_t(b.back() == '-');
            need(x / 2 != y / 2, "unary Billi bubble");
            const auto component = split.query(x / 2, x & 1u, y / 2, y & 1u);
            need(component.status == vg_native_split::Status::SEPARABLE_EXACT,
                 "Billi bubble is not separable at its two ends");
            ++total;
            if (component.full_R_nodes > 0) {
                out << line << '\n';
                ++nontrivial;
                while (vgReady && vgline < line)
                    vgReady = static_cast<bool>(std::getline(vg, vgline));
                if (!vgReady || vgline != line) {
                    const bool minimal = stats::snarlMinimal(split, x, y, component, byTime, witnessQueries);
                    outside << a << '\t' << b << '\t' << (minimal ? "yes" : "no") << '\n';
                    ++missed;
                }
            }
        }
        need(in.eof() && bool(out) && bool(outside), "error reading or writing Billi bubbles");
        std::cout << "metric\tvalue\nunique_pairs\t" << total << "\nnontrivial_pairs\t" << nontrivial
                  << "\nnontrivial_absent_vg\t" << missed << "\nminimality_witness_queries\t"
                  << witnessQueries << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Billi physical filter failed: " << e.what() << '\n';
        return 1;
    }
}
