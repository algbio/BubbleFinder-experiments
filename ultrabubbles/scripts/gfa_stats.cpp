#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <numeric>
#include <chrono>


struct CSRGraph {
    int n = 0;
    int64_t m = 0;                    
    std::vector<int64_t> offset;    
        std::vector<int> dest;        
};


static inline char flip_sign(char c) { return c == '+' ? '-' : '+'; }

struct RawEdge { int u, v; char su, sv; };

struct ParseResult {
    int n;
    std::vector<std::string> id2name;
    std::vector<RawEdge> edges;
};

static ParseResult parse_gfa(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) { fprintf(stderr, "Cannot open %s\n", path); exit(1); }

    std::unordered_map<std::string, int> name2id;
    std::vector<std::string> id2name;
    std::vector<RawEdge> edges;

    auto get_id = [&](const char* s, size_t len) -> int {
        std::string key(s, len);
        auto it = name2id.find(key);
        if (it != name2id.end()) return it->second;
        int id = (int)id2name.size();
        name2id[key] = id;
        id2name.push_back(std::move(key));
        return id;
    };

    char* line = nullptr;
    size_t cap = 0;
    ssize_t len;

    while ((len = getline(&line, &cap, f)) > 0) {
        if (len > 0 && line[len-1] == '\n') line[--len] = '\0';
        if (len > 0 && line[len-1] == '\r') line[--len] = '\0';

        if (line[0] == 'S' && line[1] == '\t') {
            char* p1 = line + 2;
            char* p2 = strchr(p1, '\t');
            size_t nlen = p2 ? (size_t)(p2 - p1) : strlen(p1);
            get_id(p1, nlen); 
        }
        else if (line[0] == 'L' && line[1] == '\t') {
            char* p = line + 2;

            char* tab1 = strchr(p, '\t');
            if (!tab1) continue;
            size_t from_len = (size_t)(tab1 - p);
            int u = get_id(p, from_len);

            char o1 = tab1[1]; 
            char* tab2 = strchr(tab1 + 1, '\t');
            if (!tab2) continue;

            char* p3 = tab2 + 1;
            char* tab3 = strchr(p3, '\t');
            if (!tab3) continue;
            size_t to_len = (size_t)(tab3 - p3);
            int v = get_id(p3, to_len);

            char o2 = tab3[1];

            char sv = flip_sign(o2);
            edges.push_back({u, v, o1, sv});
        }
    }

    free(line);
    fclose(f);

    return { (int)id2name.size(), std::move(id2name), std::move(edges) };
}


static CSRGraph build_csr(int n, const std::vector<RawEdge>& edges) {
    CSRGraph g;
    g.n = n;
    g.m = (int64_t)edges.size();
    g.offset.assign(n + 1, 0);

    for (auto& e : edges) {
        g.offset[e.u + 1]++;
        g.offset[e.v + 1]++;
    }
    for (int i = 1; i <= n; i++) {
        g.offset[i] += g.offset[i - 1];
    }

    g.dest.resize((size_t)(2 * g.m));
    std::vector<int64_t> pos(g.offset.begin(), g.offset.end());

    for (auto& e : edges) {
        g.dest[(size_t)pos[e.u]++] = e.v;
        g.dest[(size_t)pos[e.v]++] = e.u;
    }

    return g;
}


static std::vector<bool> compute_tips(int n, const std::vector<RawEdge>& edges) {
    std::vector<uint8_t> signs(n, 0);  

    for (auto& e : edges) {
        if (e.su == '+') signs[e.u] |= 1; else signs[e.u] |= 2;
        if (e.sv == '+') signs[e.v] |= 1; else signs[e.v] |= 2;
    }

    std::vector<bool> is_tip(n, false);
    for (int v = 0; v < n; v++) {
        if (signs[v] != 3 && signs[v] != 0) {
            is_tip[v] = true;
        }
    }
    return is_tip;
}

static std::vector<int> compute_cc(const CSRGraph& g) {
    if (g.n == 0) return {};
    std::vector<int> comp(g.n, -1);
    std::vector<int> stack;
    stack.reserve(std::min(g.n, 1 << 20));
    int cc = 0;

    for (int s = 0; s < g.n; s++) {
        if (comp[s] >= 0) continue;
        stack.push_back(s);
        comp[s] = cc;
        while (!stack.empty()) {
            int v = stack.back(); stack.pop_back();
            for (int64_t i = g.offset[v]; i < g.offset[v + 1]; i++) {
                int u = g.dest[(size_t)i];
                if (comp[u] < 0) {
                    comp[u] = cc;
                    stack.push_back(u);
                }
            }
        }
        cc++;
    }
    return comp;
}


static std::vector<bool> compute_cut_vertices(const CSRGraph& g) {
    if (g.n == 0) return {};
    std::vector<bool> is_cut(g.n, false);
    std::vector<int> disc(g.n, -1);
    std::vector<int> low(g.n, -1);
    std::vector<int> parent(g.n, -1);

    struct Frame {
        int v;
        int64_t ei;    
    };

    std::vector<Frame> stack;
    stack.reserve(std::min(g.n, 1 << 20));
    int timer = 0;

    for (int s = 0; s < g.n; s++) {
        if (disc[s] >= 0) continue;

        disc[s] = low[s] = timer++;
        parent[s] = -1;
        int root_children = 0;

        stack.push_back({s, g.offset[s]});

        while (!stack.empty()) {
            auto& [v, ei] = stack.back();

            bool pushed = false;
            while (ei < g.offset[v + 1]) {
                int u = g.dest[(size_t)ei];
                ei++;

                if (disc[u] < 0) {
                    disc[u] = low[u] = timer++;
                    parent[u] = v;
                    if (v == s) root_children++;

                    stack.push_back({u, g.offset[u]});
                    pushed = true;
                    break;
                } else if (u != parent[v]) {
                    if (disc[u] < low[v]) {
                        low[v] = disc[u];
                    }
                }
            }

            if (!pushed) {
                stack.pop_back();
                if (!stack.empty()) {
                    int p = stack.back().v;
                    if (low[v] < low[p]) low[p] = low[v];
                    if (parent[p] != -1 && low[v] >= disc[p]) {
                        is_cut[p] = true;
                    }
                }
            }
        }

        if (root_children > 1) {
            is_cut[s] = true;
        }
    }

    return is_cut;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <file.gfa> [file2.gfa ...]\n", argv[0]);
        fprintf(stderr, "  For .gz files: zcat file.gfa.gz | %s /dev/stdin\n", argv[0]);
        return 1;
    }

    for (int fi = 1; fi < argc; fi++) {
        const char* path = argv[fi];
        auto t0 = std::chrono::steady_clock::now();

        fprintf(stderr, "=== Processing: %s ===\n", path);

        fprintf(stderr, "  Parsing GFA...\n");
        auto parsed = parse_gfa(path);
        auto t1 = std::chrono::steady_clock::now();
        fprintf(stderr, "  Parsed %d segments, %zu links (%.1fs)\n",
                parsed.n, parsed.edges.size(),
                std::chrono::duration<double>(t1 - t0).count());

        if (parsed.n == 0) {
            printf("\n=== %s ===\n", path);
            printf("  Empty graph (0 nodes, 0 edges). Skipping.\n\n");
            fprintf(stderr, "  Empty graph, skipping.\n");
            continue;
        }

        fprintf(stderr, "  Building CSR graph...\n");
        auto g = build_csr(parsed.n, parsed.edges);
        auto t2 = std::chrono::steady_clock::now();
        fprintf(stderr, "  Built CSR: %d nodes, %lld edges (%.1fs)\n",
                g.n, (long long)g.m,
                std::chrono::duration<double>(t2 - t1).count());

        fprintf(stderr, "  Computing tips...\n");
        auto is_tip = compute_tips(parsed.n, parsed.edges);
        auto t3 = std::chrono::steady_clock::now();
        fprintf(stderr, "  Tips computed (%.1fs)\n",
                std::chrono::duration<double>(t3 - t2).count());

        fprintf(stderr, "  Computing connected components...\n");
        auto comp = compute_cc(g);
        int n_cc = comp.empty() ? 0 : *std::max_element(comp.begin(), comp.end()) + 1;
        auto t4 = std::chrono::steady_clock::now();
        fprintf(stderr, "  Found %d components (%.1fs)\n", n_cc,
                std::chrono::duration<double>(t4 - t3).count());

        fprintf(stderr, "  Computing cut vertices...\n");
        auto is_cut = compute_cut_vertices(g);
        auto t5 = std::chrono::steady_clock::now();
        fprintf(stderr, "  Cut vertices computed (%.1fs)\n",
                std::chrono::duration<double>(t5 - t4).count());
        struct CCStats {
            int64_t nodes = 0;
            int64_t edges = 0;
            int64_t tips = 0;
            int64_t cuts = 0;
            int64_t either = 0;
            bool has_start = false;
        };

        std::vector<CCStats> stats(n_cc);
        for (int v = 0; v < g.n; v++) {
            int c = comp[v];
            stats[c].nodes++;
            if (is_tip[v]) stats[c].tips++;
            if (is_cut[v]) stats[c].cuts++;
            if (is_tip[v] || is_cut[v]) stats[c].either++;
        }
        for (int v = 0; v < g.n; v++) {
            for (int64_t i = g.offset[v]; i < g.offset[v + 1]; i++) {
                int u = g.dest[(size_t)i];
                if (u > v) stats[comp[v]].edges++;
            }
        }

        for (int c = 0; c < n_cc; c++) {
            stats[c].has_start = (stats[c].tips > 0 || stats[c].cuts > 0);
        }

        std::vector<int> order(n_cc);
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(), [&](int a, int b) {
            return stats[a].nodes > stats[b].nodes;
        });
        int64_t total_tips = 0, total_cuts = 0, total_either = 0;
        int bad_cc = 0;        
        int tipless_cc = 0;    
        int cutless_cc = 0;    
        int trivial_cc = 0;    
        int64_t min_tips = INT64_MAX, min_cuts = INT64_MAX, min_either = INT64_MAX;

        for (int c = 0; c < n_cc; c++) {
            total_tips += stats[c].tips;
            total_cuts += stats[c].cuts;
            total_either += stats[c].either;
            if (!stats[c].has_start) bad_cc++;
            if (stats[c].nodes <= 1) {
                trivial_cc++;
            } else {  
                if (stats[c].tips == 0) tipless_cc++;
                if (stats[c].cuts == 0) cutless_cc++;
                min_tips = std::min(min_tips, stats[c].tips);
                min_cuts = std::min(min_cuts, stats[c].cuts);
                min_either = std::min(min_either, stats[c].either);
            }
        }

        auto t6 = std::chrono::steady_clock::now();
        double total_time = std::chrono::duration<double>(t6 - t0).count();

        printf("\n");
        printf("=== %s ===\n", path);
        printf("  Nodes:                %12d\n", g.n);
        printf("  Edges:                %12lld\n", (long long)g.m);
        printf("  Connected components: %12d\n", n_cc);
        printf("  Total tips:           %12lld  (%.2f%% of nodes)\n",
               (long long)total_tips, g.n > 0 ? 100.0 * total_tips / g.n : 0.0);
        printf("  Total cut vertices:   %12lld  (%.2f%% of nodes)\n",
               (long long)total_cuts, g.n > 0 ? 100.0 * total_cuts / g.n : 0.0);
        printf("  Total tips ∪ cuts:    %12lld  (%.2f%% of nodes)\n",
               (long long)total_either, g.n > 0 ? 100.0 * total_either / g.n : 0.0);
        printf("  CCs without start:    %12d\n", bad_cc);
        printf("  Trivial CCs (isolat.):%12d\n", trivial_cc);
        printf("  Non-triv. w/o tips:   %12d\n", tipless_cc);
        printf("  Non-triv. w/o cut vtx:%12d\n", cutless_cc);
        if (min_either != INT64_MAX) {
            printf("  Min tips/CC (non-trivial):  %8lld\n", (long long)min_tips);
            printf("  Min cuts/CC (non-trivial):  %8lld\n", (long long)min_cuts);
            printf("  Min either/CC (non-trivial):%8lld\n", (long long)min_either);
        }
        printf("  Time:                 %12.1fs\n", total_time);

        if (bad_cc == 0) {
            printf("\n   all components have at least one tip or cut vertex.\n");
        } else {
        }
        int show = std::min(n_cc, 10);
        printf("\n  Top %d components by size:\n", show);
        printf("  %6s %12s %12s %10s %10s %10s %10s\n",
               "CC#", "Nodes", "Edges", "Tips", "CutVtx", "Tips∪Cut", "HasStart");
        printf("  %s\n", std::string(76, '-').c_str());

        for (int i = 0; i < show; i++) {
            int c = order[i];
            printf("  %6d %12lld %12lld %10lld %10lld %10lld %10s\n",
                   c,
                   (long long)stats[c].nodes,
                   (long long)stats[c].edges,
                   (long long)stats[c].tips,
                   (long long)stats[c].cuts,
                   (long long)stats[c].either,
                   stats[c].has_start ? "YES" : "NO");
        }
        printf("\n");
    }

    return 0;
}
