// C++20 High-Speed APSP & Spot-Collecting Tie-Breaker Accelerator for Procon 2026 HEXUDON
// Compiled into hexudon_fast.dll via: g++ -O3 -march=native -std=c++20 -shared -static -o hexudon_fast.dll cpp_accel.cpp

#include <cstdint>
#include <queue>
#include <tuple>
#include <vector>

extern "C" {

// Terrain types:
// 0 = PLAIN (2 steps, 1 fuel)
// 1 = MOUNTAIN (3 steps, 2 fuel)
// 2 = POND (impassable)
// 3 = ROAD (1/2/4 steps by road_state, 2 fuel)

// mode:
// 0 = steps primary, fuel secondary, max spots tertiary
// 1 = fuel primary, steps secondary, max spots tertiary
// 2 = balanced (steps * 2 + fuel) primary, steps secondary, max spots tertiary
// 3 = fuel-conservative (steps + fuel * 3) primary, fuel secondary, max spots tertiary

__declspec(dllexport) void compute_apsp_cpp(
    int32_t width,
    int32_t height,
    const int32_t* terrains,     // length N = width * height
    const int32_t* road_states,  // length N (0=SMOOTH, 1=CONGESTED, 2=JAM)
    const int32_t* is_spot,      // length N (1 if cell has an active Spot, 0 otherwise)
    int32_t mode,
    int32_t* out_steps,          // length N * N
    int32_t* out_fuel,           // length N * N
    int32_t* out_parent          // length N * N
) {
    const int32_t N = width * height;
    const int32_t INF = 1000000000;

    std::vector<int32_t> step_cost(N, 0);
    std::vector<int32_t> fuel_cost(N, 0);
    std::vector<int32_t> adj_count(N, 0);
    std::vector<int32_t> adj_flat(N * 6, -1);

    const int32_t even_dr[6] = {0, 0, -1, -1, 1, 1};
    const int32_t even_dc[6] = {-1, 1, 0, 1, 0, 1};
    const int32_t odd_dr[6]  = {0, 0, -1, -1, 1, 1};
    const int32_t odd_dc[6]  = {-1, 1, -1, 0, -1, 0};

    for (int32_t u = 0; u < N; ++u) {
        int32_t t = terrains[u];
        if (t == 0) {
            step_cost[u] = 2;
            fuel_cost[u] = 1;
        } else if (t == 1) {
            step_cost[u] = 3;
            fuel_cost[u] = 2;
        } else if (t == 3) {
            int32_t rs = road_states[u];
            step_cost[u] = (rs == 0) ? 1 : ((rs == 1) ? 2 : 4);
            fuel_cost[u] = 2;
        }

        int32_t r = u / width;
        int32_t c = u % width;
        const int32_t* dr = (r % 2 == 0) ? even_dr : odd_dr;
        const int32_t* dc = (r % 2 == 0) ? even_dc : odd_dc;

        int32_t cnt = 0;
        for (int k = 0; k < 6; ++k) {
            int32_t nr = r + dr[k];
            int32_t nc = c + dc[k];
            if (nr >= 0 && nr < height && nc >= 0 && nc < width) {
                int32_t v = nr * width + nc;
                if (terrains[v] != 2) {
                    adj_flat[u * 6 + cnt] = v;
                    cnt++;
                }
            }
        }
        adj_count[u] = cnt;
    }

    // Tuple: (primary_cost, secondary_cost, neg_spots_passed, cell_id)
    using Node = std::tuple<int32_t, int32_t, int32_t, int32_t>;
    std::vector<int32_t> best_spots(N, 0);

    for (int32_t src = 0; src < N; ++src) {
        int32_t* d_s = out_steps + (src * N);
        int32_t* d_f = out_fuel + (src * N);
        int32_t* par = out_parent + (src * N);

        for (int32_t i = 0; i < N; ++i) {
            d_s[i] = INF;
            d_f[i] = INF;
            par[i] = -1;
            best_spots[i] = -1;
        }

        if (terrains[src] == 2) {
            continue;
        }

        d_s[src] = 0;
        d_f[src] = 0;
        best_spots[src] = 0;

        std::priority_queue<Node, std::vector<Node>, std::greater<Node>> pq;
        pq.emplace(0, 0, 0, src);

        while (!pq.empty()) {
            auto [p_cost, s_cost, neg_sp, u] = pq.top();
            pq.pop();

            int32_t cur_s = d_s[u];
            int32_t cur_f = d_f[u];
            int32_t cur_sp = best_spots[u];

            if (mode == 0) {
                if (p_cost > cur_s || (p_cost == cur_s && s_cost > cur_f) ||
                    (p_cost == cur_s && s_cost == cur_f && -neg_sp < cur_sp)) continue;
            } else if (mode == 1) {
                if (p_cost > cur_f || (p_cost == cur_f && s_cost > cur_s) ||
                    (p_cost == cur_f && s_cost == cur_s && -neg_sp < cur_sp)) continue;
            } else if (mode == 2) {
                int32_t bal = cur_s * 2 + cur_f;
                if (p_cost > bal || (p_cost == bal && s_cost > cur_s) ||
                    (p_cost == bal && s_cost == cur_s && -neg_sp < cur_sp)) continue;
            } else {
                int32_t fcon = cur_s + cur_f * 3;
                if (p_cost > fcon || (p_cost == fcon && s_cost > cur_f) ||
                    (p_cost == fcon && s_cost == cur_f && -neg_sp < cur_sp)) continue;
            }

            int32_t ns = cur_s + step_cost[u];
            int32_t nf = cur_f + fuel_cost[u];
            int32_t deg = adj_count[u];
            const int32_t* nbrs = &adj_flat[u * 6];

            for (int32_t i = 0; i < deg; ++i) {
                int32_t v = nbrs[i];
                int32_t nsp = cur_sp + (is_spot ? is_spot[v] : 0);
                bool better = false;
                int32_t np = 0, nsec = 0;

                if (mode == 0) {
                    np = ns; nsec = nf;
                    if (ns < d_s[v] || (ns == d_s[v] && nf < d_f[v]) ||
                        (ns == d_s[v] && nf == d_f[v] && nsp > best_spots[v])) better = true;
                } else if (mode == 1) {
                    np = nf; nsec = ns;
                    if (nf < d_f[v] || (nf == d_f[v] && ns < d_s[v]) ||
                        (nf == d_f[v] && ns == d_s[v] && nsp > best_spots[v])) better = true;
                } else if (mode == 2) {
                    np = ns * 2 + nf; nsec = ns;
                    int64_t old_p = static_cast<int64_t>(d_s[v]) * 2 + static_cast<int64_t>(d_f[v]);
                    if (np < old_p || (np == old_p && ns < d_s[v]) ||
                        (np == old_p && ns == d_s[v] && nsp > best_spots[v])) better = true;
                } else {
                    np = ns + nf * 3; nsec = nf;
                    int64_t old_p = static_cast<int64_t>(d_s[v]) + static_cast<int64_t>(d_f[v]) * 3;
                    if (np < old_p || (np == old_p && nf < d_f[v]) ||
                        (np == old_p && nf == d_f[v] && nsp > best_spots[v])) better = true;
                }

                if (better) {
                    d_s[v] = ns;
                    d_f[v] = nf;
                    par[v] = u;
                    best_spots[v] = nsp;
                    pq.emplace(np, nsec, -nsp, v);
                }
            }
        }
    }
}

} // extern "C"
