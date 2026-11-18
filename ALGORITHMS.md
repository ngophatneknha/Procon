# HEXUDON — Mô tả chi tiết từng thuật toán

Tài liệu này mô tả **mọi thành phần thuật toán** của bộ giải trong `hexudon/`, theo thứ tự chạy trong một trận. Mỗi mục có: mục đích, cách hoạt động, tham số/công tắc, chi phí, và hiệu quả đã đo (xem [RESULTS.md](RESULTS.md); mọi số liệu đo trên map tự sinh, chưa phải map thật của BTC).

## 0. Bức tranh tổng thể

```
Trước trận                                        Mỗi ngày (plan_day)
──────────                                        ───────────────────
select_roles                                      1. APSP 3 chế độ (C++/Python)
  ├─ A. Sinh ứng viên (mọi tập xe tiếp xăng)      2. Phase 1  Portfolio xác định
  ├─ B. Rollout rẻ → lọc top 5                    3. Phase 2  Rollout ngẫu nhiên có seed
  ├─ C. Rollout đầy đủ → top 3 vai trò            4. Phase 2b Portfolio heuristic H1–H7
  ├─ D. Chơi thử 3 vai trò × 3 seed               5. Phase 3  Local search lộ trình (2-opt, chèn, đổi)
  └─ E. (1+1)-ES hệ số ưu tiên (ngày, quán)       6. Phase 3b ILS trên lộ trình từng xe
                                                  7. Phase 4  Lookahead (1 ngày hoặc cả trận)
                                                  → chọn lịch tốt nhất, kiểm bằng engine
```

Nguyên tắc xuyên suốt: **mọi lịch ứng viên đều được `HexudonEngine.simulate_day` kiểm tra tuyệt đối đúng luật trước khi chọn**, nên bộ giải không bao giờ gửi lệnh invalid.

Hàm chấm một ngày (`_evaluate_day_result`) trả về khóa so sánh từ điển:
`(chuỗi mới toàn trận, chuỗi khác nhau trong ngày, số phần, tổng xăng cuối ngày, số xe đỗ ở quán, thưởng gần quán chưa ghé)` — khớp thứ tự F1 > F2 > F3 của đề, các thành phần sau chỉ để phá hòa theo hướng có lợi cho ngày kế tiếp.

---

## 1. Hình học lục giác và Dijkstra đa tiêu chí (`engine.py: HexGrid`)

**Mục đích:** biểu diễn bản đồ `even-r` và tính đường đi ngắn nhất theo luật "chi phí theo ô xuất phát".

- Ô `id = r*W + c`. Hàng chẵn lệch phải nửa ô. 6 láng giềng hàng chẵn: `(0,-1),(0,1),(-1,0),(-1,1),(1,0),(1,1)`; hàng lẻ: `(0,-1),(0,1),(-1,-1),(-1,0),(1,-1),(1,0)`.
- Khoảng cách lục giác: đổi sang tọa độ trục `q = c - (r + (r&1))//2` rồi `max(|dq|,|dr|,|dq+dr|)`.
- **Dijkstra** `shortest_paths_from(src, road_states, optimize_for)`: trọng số cạnh `u→v` lấy theo **ô u** (số bước và xăng của địa hình tại u; đường bộ theo trạng thái thông thoáng/đông/tắc). Ao bị loại. Khóa ưu tiên theo chế độ:
  - `steps`: (bước, xăng) · `fuel`: (xăng, bước) · `balanced`: (2·bước + xăng, bước).
- Trả về `dist_steps`, `dist_fuel`, `parent` để dựng lại đường.

## 2. APSP tăng tốc C++ (`cpp_accel.cpp`, `fast_apsp.py`)

**Mục đích:** tính khoảng cách ngắn nhất giữa MỌI cặp ô (tới 1024×1024) nhanh, vì mọi thành phần phía sau đều cần bảng này.

- Lõi C++20 chạy Dijkstra từ mọi nguồn, 4 chế độ: `steps`, `fuel`, `balanced` (2·bước+xăng), `fuel_heavy` (bước+3·xăng).
- **Phá hòa theo quán (`-nsp`):** khi hai đường bằng nhau về (bước, xăng), chọn đường đi qua **nhiều ô quán hơn**, để xe thu udon "miễn phí" dọc đường.
- Lỗi đã sửa: tràn số 32-bit ở chế độ `balanced` (`INF=1e9` nhân đôi) → ép `int64`.
- `fast_apsp.py` gọi DLL bằng `ctypes`, cắt lát trực tiếp từ buffer; nếu không có DLL thì tự rơi về Dijkstra Python.
- Bộ nhớ đệm `_apsp_cache` trong solver khóa theo (trạng thái đường, chế độ), **giới hạn 24 mục** (xóa hết khi vượt) để không tràn RAM trên map 32×32.

## 3. Mô phỏng và kiểm định (`engine.py: HexudonEngine`)

**Mục đích:** mô phỏng từng bước đúng luật và là "trọng tài" cho mọi ứng viên.

Luật được cài: chi phí theo ô xuất phát; `MOVE` bị từ chối khi không kề, vào ao, thiếu bước, hoặc xe tuần tra thiếu xăng; mỗi bước cuối: cập nhật ô, **nạp xăng** nếu xe tuần tra chung ô với xe tiếp xăng (≥1 bước), **thu udon** (mỗi xe một phần/quán/ngày, kho giảm 1); dãy lệnh phải lấp đủ `max_steps` bằng `WAIT`. Lưu lượng đường: tổng số bước đứng của mọi xe trên ô đường, ngày 2 dùng ngày 1, ngày ≥3 dùng 2 ngày trước, chia số đội, so ngưỡng đông/tắc.

> Giả định cần xác minh với server thật: xe đang rời một ô quán vẫn thu udon ở cuối bước 1 (ô chưa đổi); lưu lượng tính mọi bước xe ở trên ô đường (kể cả bước đang rời đi).

## 4. Chọn vai trò trước trận (`solver.py: select_roles`)

**Mục đích:** chọn xe nào là tuần tra/tiếp xăng. Đo được đây là **đòn bẩy lớn nhất** (có map F1 từ 9→11, 14→17, 17→19 chỉ nhờ đổi vai trò).

Gồm 5 giai đoạn:

**A. Sinh ứng viên.** Mọi tập xe tiếp xăng kích thước 0..kmax (kmax = 2, hoặc 3 khi N ≥ 7, và luôn chừa ≥1 xe tuần tra). Bản cũ chỉ thử vài tổ hợp chọn tay theo độ trung tâm.

**B. Rollout rẻ (khi >12 ứng viên).** Với mỗi ứng viên, chơi cả trận bằng **1 cấu hình** portfolio (`_quick_rollout_roles(n_cfg=1)`), có giới hạn thời gian `role_time_s` (mặc định 8 s); giữ top 5.

**C. Rollout đầy đủ.** Top 5 chơi cả trận bằng portfolio xác định đầy đủ; xếp theo (F1, F2, F3).

**D. Chơi thử bằng bộ lập kế hoạch thật.** Rollout rẻ xếp hạng sai ở một số map (map 39, 105). Với top 3 vai trò × 3 seed `(seed, 7, 99)` chạy `_play_rollout_roles` (dùng `plan_day` thật ở ngân sách thật), giữ cặp (vai trò, seed) tốt nhất. Có giới hạn `role_time_s`.
- Nhờ `plan_day` **tất định theo (seed, ngày)** (mục 6.2), quỹ đạo chơi thử được tái hiện đúng khi vào trận thật (trong trường hợp 1 đội).

**E. (1+1)-ES hệ số ưu tiên (ngày, quán)** — xem mục 9.

Công tắc: `HEX_OLD_ROLES=1` (cách cũ), `HEX_PLAYSEL=0` (bỏ giai đoạn D), `HEX_ES=0` (bỏ giai đoạn E).
Chi phí: ≈ 30–45 s trên map 32×32/8 xe (chỉnh `role_time_s`, `evolve_time_s`, hoặc `HEX_ES_TIME`).

## 5. Bảy heuristic H1–H7 (`heuristics.py`)

| # | Tên | Công thức / cơ chế | Dùng ở đâu |
|---|---|---|---|
| H1 | Độ hiếm chuỗi + độ cô lập | `scarcity(c) = (1/count(c))^0.65`; `isolation(s)` = khoảng cách TB tới quán khác, chuẩn hóa. Thưởng nhân `1 + w·(0.7·scarcity + 0.3·isolation)` cho chuỗi mới trong ngày | `_build_schedule` (khi `scarcity_w>0`) |
| H2 | Trường hấp dẫn | `pot(s) = Σ stock_j·mult / (d+1)^1.4` với quán j trong ≤10 bước; `mult` = 3.5 (chuỗi mới toàn trận), 2.2 (mới trong ngày), 1.2 (còn lại) | cộng vào điểm đích (`gravity_w`) |
| H3 | Chạy nước rút tới xe tiếp xăng | Xe tiếp xăng tốn 0 xăng nên luôn đi theo `apsp_steps` (đường 1 bước/ô) để tới điểm hẹn nhanh nhất | `_try_schedule_rendezvous` |
| H4 | Độ trung gian đường bộ | Đếm số lần ô đường nằm trên đường ngắn nhất giữa mọi cặp quán, chuẩn hóa; cuối ngày xe bước khỏi ô đường sang ô đồng bằng trước khi `WAIT` để khỏi tự làm tắc đường hôm sau | `_step_off_road_if_needed` |
| H5 | Giá ẩn của xăng | `shadow = min(1.2, 0.18·(max_fuel/fuel)·f(khoảng cách tới xe tiếp xăng))`; điểm đích = `reward / (bước + shadow·xăng + 1)` | `_build_schedule` |
| H6 | Đấu giá Regret-2 | Nếu xe khác tới quán đó muộn hơn >2 bước thì thưởng `+2.5%·gap` (tối đa 12); nếu xe khác tới sớm hơn >2 bước thì phạt ×0.8 | `_build_schedule` |
| H7 | Ghé quán trên đường | Với đích `v`, tìm quán trung gian `w` làm thêm ≤0 bước (≤2 nếu `w` mở chuỗi mới trong ngày) mà vẫn đủ bước/xăng tới `v` | `find_best_via_spot` |

## 6. Lập kế hoạch một ngày (`plan_day`)

### 6.1 Bộ dựng lịch tham lam (`_build_schedule`)
Lõi của mọi ứng viên. Mỗi xe tuần tra lần lượt chọn **đích kế tiếp** theo điểm:

`score = reward / (bước + shadow·xăng + 1) + lookahead_bonus + gravity − cluster_bias·khoảng_cách_neo` rồi nhân nhiễu `(1±noise)` và **hệ số ưu tiên (ngày, quán)** của mục 9.

- `reward = 100 + 1.000.000 (chuỗi mới toàn trận) + 15.000 (chuỗi mới trong ngày)` → bám đúng thứ tự F1 ≫ F2 ≫ F3.
- `lookahead_bonus`: giá trị tốt nhất của quán tiếp theo sau đích (nhìn trước 1 bước).
- Đích phải khả thi theo bước còn lại và xăng; nếu không đủ xăng thì chuyển sang bản đồ `fuel` hoặc gọi **hẹn xe tiếp xăng**.
- **Hẹn xe tiếp xăng** (`_try_schedule_rendezvous`): chọn ô hẹn và thời điểm `t_meet = max(bước xe tiếp xăng tới, bước xe tuần tra tới)`, bắt xe tiếp xăng chờ đủ ≥1 bước chung ô; trên map >256 ô thu hẹp tập ô hẹn (ô hiện tại, láng giềng, các quán, đường rb→pb) để nhanh gấp ~2×.
- Cuối ngày: bước khỏi ô đường (H4), xe tiếp xăng chặn đón xe tuần tra theo đúng thời điểm, rồi `WAIT` cho đủ bước.
- `forced_tours`: ép trước một dãy quán cho mỗi xe (dùng bởi local search/ILS).

### 6.2 Portfolio, rollout và tính tất định
- **Phase 1 – Portfolio xác định** (`_get_deterministic_portfolio`): các cấu hình (chế độ APSP, ngưỡng xăng, cluster_bias, lookahead…).
- **Phase 2 – Rollout ngẫu nhiên:** `min(600, ngân_sách_ms/15)` lần dựng với tham số rút ngẫu nhiên. Đo được **thêm rollout/thời gian ở đây không cải thiện** (thí nghiệm 11).
- **Phase 2b – Portfolio H1–H7:** cấu hình bật H1/H2/2-opt.
- **Tính tất định:** `rng` được gieo bằng `seed*1000 + ngày` ở đầu `plan_day`, và các vòng lặp dùng **số lần lặp** thay vì đồng hồ. Cùng (seed, trạng thái, ngân sách) luôn cho cùng lịch → chơi thử trước trận tái hiện đúng trong trận (1 đội).

### 6.3 Local search lộ trình (`_run_tour_local_search`, Phase 3)
Chạy trên lộ trình quán của lịch tốt nhất, 3 toán tử:
1. **2-opt nội bộ** (`optimize_spot_sequence_2opt`): đảo đoạn trong dãy quán của một xe nếu giảm (bước, xăng) và không vượt ngân sách xăng.
2. **Chèn chuỗi bị sót:** chuỗi chưa thu hôm nay (ưu tiên chưa từng thu toàn trận) → chèn quán gần nhất vào vị trí 0–2 của xe có độ lệch bước nhỏ nhất, chạy lại 2-opt.
3. **Đổi chéo giữa hai xe:** hoán đổi quán ở 3 vị trí đầu của hai xe nếu giảm tổng bước.
Mỗi biến thể dựng lại lịch bằng `forced_tours` rồi qua engine.

### 6.4 ILS trên lộ trình từng xe (`_ils_tours`, Phase 3b)
Mở rộng Phase 3 từ một lượt thành **tìm kiếm lặp (ruin & recreate)**: lặp `min(200, ngân_sách/5)` lần:
- Nhiễu loạn ngẫu nhiên một trong 4 phép: **bỏ** một quán · **chèn** một quán bất kỳ vào vị trí rẻ nhất (lấy từ xe khác nếu có) · **chuyển** quán sang xe khác · **đổi chéo** hai quán giữa hai xe; rồi 2-opt xe bị đổi.
- Dựng lại ngày bằng bộ dựng tham lam với `forced_tours`, mô phỏng, chấm khóa ngày.
- **Chấp nhận nếu không tệ hơn** (`≥`, cho phép trôi ngang); ghi lại các lịch tốt hơn nghiêm ngặt làm ứng viên.
Công tắc `HEX_ILS=0`. Đo: F2 +19, F3 +20 trên 10 map; không map nào mất F1.

### 6.5 Lookahead (Phase 4)
Đánh giá các trạng thái cuối ngày khác nhau (khác vị trí/xăng) để tránh ăn tham hôm nay làm hỏng ngày mai.
- **Cũ (1 ngày):** chơi thử ngày d+1 bằng 3 cấu hình, lấy khóa 2 ngày.
- **Nhìn xa cả trận:** chơi nốt mọi ngày còn lại bằng 2 cấu hình rẻ (chỉ tính lưu lượng của chính mình), chấm `(chuỗi toàn trận, tổng chuỗi/ngày, tổng phần)`.
- Chỉ bật nhìn xa khi **F1 chưa đủ chuỗi** hoặc ngân sách ≥1500 ms (đắt 3–5×, lợi ích rõ trên map ít xe). `HEX_HORIZON=0` ép dùng bản 1 ngày.

## 7. Giá trị lộ trình / mô hình chi phí tóm tắt

Xe tiếp xăng đổi "xăng" thành "bước": H5 đặt giá ẩn của xăng tăng khi xe cạn xăng và xa xe tiếp xăng; vì vậy xe gần nhà tiếp tế đi "xa" hơn, xe xa tiếp tế đi tiết kiệm xăng hơn.

## 8. Đấu trường và đối thủ mẫu (`arena.py`)
`MultiTeamArena` chạy nhiều đội cùng lúc trên một map, chia sẻ lưu lượng đường. Đối thủ mẫu: *Greedy Dijkstra Orienteering*, *Multi-Agent Auction + Gravity*, *Voronoi + TSP 2-opt*. Dùng để kiểm tra bộ giải khi đường bị đối thủ làm tắc (khác giả định 1 đội của mục 6.2).

## 9. Tiến hóa hệ số ưu tiên (ngày, quán) — (1+1)-ES (`_evolve_bias`)

**Mục đích:** bộ dựng tham lam từng ngày không thấy được "ngày nào nên lấy quán nào" để cả trận tốt. ES học điều đó.

- **Biểu diễn:** từ điển `{(ngày, ô quán): hệ số}`, hệ số ∈ [0.1, 10], mặc định 1, nhân vào điểm đích của quán đó vào ngày đó.
- **Đột biến:** mỗi bước chọn 1–3 cặp (ngày, quán) ngẫu nhiên và nhân hệ số với {0.25, 0.5, 2, 4}.
- **Fitness:** chơi **cả trận** bằng `plan_day` thật, so sánh từ điển (F1, F2, F3). Chấp nhận nếu `≥` (cho trôi ngang).
- **Phát hiện quan trọng:** tinh chỉnh ở ngân sách rẻ (30 ms) **không** chuyển sang ngân sách thật; phải đánh giá ở ngân sách thật (`plan_budget_ms`).
- **Kiểm chứng cuối:** so lịch có hệ số với lịch không hệ số ở ngân sách thật; chỉ giữ nếu tốt hơn nghiêm ngặt.
- Thời gian `evolve_time_s` (mặc định 15 s; `HEX_ES_TIME`). Đo: F3 1882 → 1918; tăng lên 60 s không giúp thêm (bão hòa).

## 10. Gửi đáp án (`client.py`)
`MatchRunner` chạy trận nội bộ (và đặt `plan_budget_ms` = ngân sách mỗi ngày trước khi chọn vai trò). `ContestApiClient.plan_and_submit_dual_commit` gửi sớm rồi gửi lại nếu tìm được phương án tốt hơn **về F1–F3**.

> Lưu ý đã đối chiếu đề: F4 tính theo **câu trả lời hợp lệ cuối cùng**, nên gửi lại làm thời gian bị tính theo lần gửi sau (gửi sớm không "khóa" F4), và gửi quá nhiều lần có thể bị coi là gây rối. Endpoint/schema trong `client.py` chỉ là phỏng đoán đến khi BTC công bố.

## 11. Bảng công tắc môi trường

| Biến | Tác dụng |
|---|---|
| `HEX_OLD_ROLES=1` | Chọn vai trò theo cách cũ (vài tổ hợp tay, không tìm kiếm rộng) |
| `HEX_PLAYSEL=0` | Bỏ chơi thử (vai trò × seed) |
| `HEX_ES=0` / `HEX_ES_TIME=<s>` | Tắt / đổi thời gian ES |
| `HEX_ILS=0` | Tắt ILS lộ trình |
| `HEX_HORIZON=0` | Luôn dùng lookahead 1 ngày |
| `HEX_SEED=<n>` | Seed cơ sở của bench |

## 12. Hạn chế đã biết
- Tính tất định chỉ chính xác khi 1 đội; đối thủ làm đổi trạng thái đường thì lệch dần.
- Chọn vai trò + ES tốn 30–45 s trước trận trên map lớn; phải chỉnh theo thời gian BTC cho.
- Map ít xe/ít ngày vẫn có thể thiếu chuỗi (map 39: 17–18/20).
- Mọi kết quả đo trên map tự sinh; thông số thật (số đội, ngưỡng đường, giới hạn thời gian, schema API) chưa có.
