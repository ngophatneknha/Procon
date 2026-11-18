# HEXUDON — Tài liệu thuật toán chi tiết

Tài liệu mô tả **từng thuật toán** của bộ giải trong `hexudon/`: mục đích, công thức, giả mã, ví dụ số, tham số, độ phức tạp, **cách chạy riêng từng thuật toán**, và hiệu quả đã đo.
Số liệu đo xem [RESULTS.md](RESULTS.md). Mọi số liệu được đo trên map tự sinh bởi `generator.py`, **chưa phải map thật của BTC**.

## Mục lục
0. Cài đặt và cách chạy nhanh
1. Bức tranh tổng thể và khóa chấm
2. Hình học lục giác và Dijkstra theo ô xuất phát
3. APSP tăng tốc C++
4. Bộ mô phỏng và kiểm định luật
5. Chọn vai trò xe trước trận
6. Bảy heuristic H1–H7
7. Bộ dựng lịch tham lam một ngày
8. Hẹn xe tiếp xăng (rendezvous)
9. Local search lộ trình: 2-opt, chèn, đổi chéo
10. ILS trên lộ trình từng xe
11. Lookahead (1 ngày và cả trận)
12. Tiến hóa hệ số ưu tiên (1+1)-ES
13. Tính tất định và chơi thử
14. Đấu trường đối thủ mẫu
15. Gửi đáp án lên server
16. Bảng tham số và công tắc môi trường
17. Hạn chế đã biết

---

## 0. Cài đặt và cách chạy nhanh

**Yêu cầu:** Python 3.11. Tùy chọn: `g++` (MSYS2 UCRT64) để biên dịch lại DLL; nếu không có DLL thì tự dùng Dijkstra Python (chậm hơn).
Chỉ dùng thư viện chuẩn, không cần `pip install`. (`PyMuPDF` chỉ dùng khi muốn đọc PDF đề.)

```bash
cd E:\procon
python -m unittest tests/test_hexudon.py -v        # 8 test luật + C++ vs Python + end-to-end (~40 s vì có ES)
python run_benchmark.py                            # 4 kịch bản 1 đội + giải đấu 4 đội, ghi sample_replays.json
python build_visualizer.py                         # tạo visualizer.html (mở bằng trình duyệt)
python bench_wide.py 12 120                        # 12 map ngẫu nhiên, ngân sách 120 ms/ngày
python bench_wide.py 0 120 39,13,105               # chỉ chạy các map id 39, 13, 105
python exp_roles.py 39 13                          # thử MỌI tập xe tiếp xăng trên map 39, 13
```

Biên dịch lại lõi C++ (khi sửa `hexudon/cpp_accel.cpp`):

```bash
C:\msys64\ucrt64\bin\g++.exe -O3 -march=native -std=c++20 -shared -static -o E:\procon\hexudon\hexudon_fast.dll E:\procon\hexudon\cpp_accel.cpp
```

Bật/tắt thuật toán bằng biến môi trường (xem mục 16):

```powershell
$env:HEX_ES="0"; $env:HEX_ILS="0"; python bench_wide.py 0 120 39     # PowerShell
```
```bash
HEX_ES=0 HEX_ILS=0 python bench_wide.py 0 120 39                       # bash
```

> **Bộ nhớ:** `bench_wide.py` và `exp_roles.py` dùng `Pool(2, maxtasksperchild=1)`. Đừng tăng lên 8 tiến trình: bảng APSP của map 32×32 rất lớn và đã từng làm tràn RAM.

**Chạy một trận đầy đủ bằng code:**

```python
from hexudon.generator import generate_map_config
from hexudon.client import MatchRunner
from hexudon.solver import HexudonSolver

cfg = generate_map_config(width=16, height=14, num_agents=6, num_spots=24,
                          num_chains=14, num_days=6, max_fuel=18, seed=2026)
solver = HexudonSolver(cfg, seed=42)
solver.role_time_s = 8.0        # giới hạn mỗi giai đoạn chọn vai trò (giây)
solver.evolve_time_s = 15.0     # giới hạn ES (giây)
replay = MatchRunner(cfg, solver).run_match(time_budget_ms_per_day=120.0)
print(replay["roles"], replay["score"])
```

---

## 1. Bức tranh tổng thể và khóa chấm

```
TRƯỚC TRẬN  select_roles (mục 5)                 MỖI NGÀY  plan_day
  A. Sinh mọi tập xe tiếp xăng                     1. APSP 3 chế độ: steps / fuel / balanced
  B. Rollout rẻ → top 5                            2. Phase 1  portfolio xác định (6 cấu hình)
  C. Rollout đầy đủ → top 3 vai trò                3. Phase 2  rollout ngẫu nhiên có seed
  D. Chơi thử 3 vai trò × 3 seed                   4. Phase 2b portfolio heuristic H1–H7 (3 cấu hình)
  E. (1+1)-ES hệ số (ngày, quán)  (mục 12)         5. Phase 3  local search 2-opt/chèn/đổi (mục 9)
                                                   6. Phase 3b ILS lộ trình từng xe (mục 10)
                                                   7. Phase 4  lookahead (mục 11)
                                                   → trả lịch tốt nhất, đã qua engine
```

**Nguyên tắc an toàn:** mọi lịch ứng viên đều chạy qua `HexudonEngine.simulate_day`; chỉ lịch hợp lệ mới được xét. Nếu không có ứng viên hợp lệ, trả `WAIT` toàn bộ (luôn hợp lệ).

**Khóa chấm một ngày** (`_evaluate_day_result`), so sánh từ điển, lớn hơn là tốt hơn:

$$K = \big(\,N_{new},\; N_{day},\; P,\; \Phi,\; \Pi,\; B\,\big)$$

| Thành phần | Ý nghĩa |
|---|---|
| $N_{new}$ | số chuỗi chưa từng thu trước ngày này nhưng thu hôm nay (→ F1) |
| $N_{day}$ | số chuỗi khác nhau thu hôm nay (→ F2) |
| $P$ | số phần udon hôm nay (→ F3) |
| $\Phi$ | tổng xăng còn lại của xe tuần tra cuối ngày |
| $\Pi$ | số xe tuần tra đang đỗ trên ô quán còn ≥1 xăng (chỉ khi chưa phải ngày cuối) |
| $B$ | $-0.15\sum_{\text{xe}}\min_{s\in U} d(\text{cuối}, s) - 0.02\cdot(\text{tổng bước đứng trên đường})$, với $U$ = các quán thuộc chuỗi còn chưa thu |

$N_{new},N_{day},P$ bám đúng F1 > F2 > F3 của đề; $\Phi,\Pi,B$ chỉ phá hòa theo hướng có lợi cho ngày kế tiếp (còn xăng, đứng sẵn gần chuỗi chưa thu, không tự làm tắc đường).

---

## 2. Hình học lục giác và Dijkstra theo ô xuất phát (`engine.py: HexGrid`)

**Mục đích:** biểu diễn lưới `even-r` và tìm đường ngắn nhất theo luật "chi phí tính theo ô đang đứng".

**Chỉ số ô:** $id = r\cdot W + c$, $r=\lfloor id/W\rfloor$, $c = id \bmod W$.

**Láng giềng** (hàng chẵn lệch phải nửa ô, Hình 1 của đề):

| Hàng | 6 độ lệch $(\Delta r,\Delta c)$ |
|---|---|
| chẵn ($r \bmod 2=0$) | $(0,-1),(0,1),(-1,0),(-1,1),(1,0),(1,1)$ |
| lẻ ($r \bmod 2=1$) | $(0,-1),(0,1),(-1,-1),(-1,0),(1,-1),(1,0)$ |

**Khoảng cách lục giác:** đổi sang tọa độ trục rồi

$$q = c - \left\lfloor \tfrac{r + (r \,\&\, 1)}{2}\right\rfloor,\qquad d_{hex}(a,b)=\tfrac{|q_a-q_b|+|r_a-r_b|+|(q_a-q_b)+(r_a-r_b)|}{2}$$

**Chi phí một bước đi $u\to v$ (luật ô xuất phát, Bảng 1):**

| Địa hình của $u$ | bước | xăng |
|---|---|---|
| Đồng bằng | 2 | 1 |
| Núi | 3 | 2 |
| Đường thông thoáng / đông / tắc | 1 / 2 / 4 | 2 |
| Ao | không vào được ($v$ là ao ⇒ cạnh bị loại) | — |

**Dijkstra** `shortest_paths_from(src, road_states, optimize_for)`: cạnh $u\to v$ có trọng số $(s_u, f_u)$ tra theo bảng trên. Khóa ưu tiên trong hàng đợi:

| `optimize_for` | khóa so sánh |
|---|---|
| `steps` | $(\text{bước}, \text{xăng})$ |
| `fuel` | $(\text{xăng}, \text{bước})$ |
| `balanced` | $(2\cdot\text{bước}+\text{xăng},\ \text{bước})$ |

Trả về `dist_steps`, `dist_fuel`, `parent`; `reconstruct_path(parent, src, dst)` trả danh sách ô $[v_1,\dots,dst]$.

**Độ phức tạp:** $O(E\log V)$ mỗi nguồn, $V\le1024$, $E\approx 6V$.

```python
from hexudon.engine import HexGrid
grid = HexGrid(cfg.width, cfg.height, cfg.terrains)
grid.hex_distance(0, 50)                                   # khoảng cách lục giác
ds, df, par = grid.shortest_paths_from(0, {}, "steps")     # Dijkstra từ ô 0
path = grid.reconstruct_path(par, 0, 50)                   # đường đi
```

---

## 3. APSP tăng tốc C++ (`cpp_accel.cpp`, `fast_apsp.py`)

**Mục đích:** tính khoảng cách ngắn nhất giữa **mọi cặp ô** nhanh. Mọi thành phần phía sau (chọn đích, hẹn, local search) đều tra bảng này.

- Chạy Dijkstra từ mọi nguồn trong C++20; 4 chế độ: `steps`, `fuel`, `balanced` $=2s+f$, `fuel_heavy` $=s+3f$.
- **Phá hòa theo quán (`-nsp`):** khóa ưu tiên có thành phần cuối $-n_{spot}$ = trừ số ô quán đi qua. Khi hai đường bằng nhau về $(s,f)$, chọn đường đi qua **nhiều quán hơn** để xe thu udon "miễn phí" dọc đường.
- **Lỗi đã sửa:** `INF = 10^9` nhân 2 ở chế độ `balanced` tràn số có dấu 32-bit ⇒ ép `int64`.
- `fast_apsp.py` gọi DLL qua `ctypes`; nếu không nạp được DLL thì `compute_apsp_fast` trả `None` và solver rơi về Dijkstra Python.
- **Bộ nhớ đệm:** `solver._apsp_cache` khóa theo (trạng thái đường, chế độ), xóa sạch khi >24 mục (tránh tràn RAM trên 32×32).

```python
from hexudon.engine import HexudonEngine
from hexudon.fast_apsp import compute_apsp_fast, has_cpp_accelerator
print(has_cpp_accelerator())                               # True nếu có hexudon_fast.dll
rs = HexudonEngine(cfg).compute_road_states([], 1)         # ngày 1: toàn đường thông thoáng
steps, fuel, parent = compute_apsp_fast(cfg, rs, mode="steps")
print(steps[u][v], fuel[u][v])                             # bước, xăng ngắn nhất u→v
```

---

## 4. Bộ mô phỏng và kiểm định luật (`engine.py: HexudonEngine`)

**Mục đích:** mô phỏng từng bước đúng luật; là "trọng tài" cho mọi ứng viên và cho bản chạy cuối.

**Vòng lặp mỗi bước** $t=1..max\_steps$:
1. Mỗi xe rảnh nhận lệnh kế: `WAIT(k)` (cần $k\le$ bước còn lại) hoặc `MOVE(v)`.
2. `MOVE(u→v)` bị **từ chối (invalid)** nếu: $v$ không kề $u$; $v$ là ao; bước còn lại $<s_u$; xe tuần tra có xăng $<f_u$. Nếu hợp lệ: xe bận $s_u$ bước, trừ ngay $f_u$ xăng (xe tuần tra).
3. Hết một bước: mọi xe giảm bộ đếm bận; xe nào đếm về 0 và đang đi thì chuyển sang $v$. Cộng 1 vào "số bước đứng" của ô đường mà xe đang ở (cho lưu lượng).
4. **Nạp xăng:** xe tuần tra cùng ô với xe tiếp xăng ⇒ xăng = `max_fuel`.
5. **Thu udon:** xe tuần tra ở ô quán chưa ghé hôm nay và kho $>0$ ⇒ kho −1, +1 phần, thêm chuỗi.
6. Hết ngày: mỗi xe phải dùng hết đúng `max_steps` (không còn lệnh thừa/thiếu).

**Trạng thái đường** $\rho$ (đầu ngày $d$):

$$\text{traffic}(u)=\frac{\sum_{k\in\text{2 ngày trước}} stay_k(u)}{num\_teams},\quad
\text{state}=\begin{cases}\text{SMOOTH}&<T_c\\ \text{CONGESTED}&T_c\le\cdot<T_j\\ \text{JAM}&\ge T_j\end{cases}$$

Ngày 1 toàn thông thoáng; ngày 2 chỉ dùng ngày 1; ngày ≥3 dùng ngày $d-1$ và $d-2$.

**Ví dụ số:** `num_teams=4`, $T_c=3,T_j=6$; ô đường $u$ có 10 bước đứng ngày 3 và 6 bước ngày 2 ⇒ traffic $=(10+6)/4=4$ ⇒ $3\le4<6$ ⇒ CONGESTED ⇒ đi ra khỏi ô này mất 2 bước.

> Giả định cần xác minh với server thật: (a) xe đang rời một ô quán vẫn thu udon ở cuối bước 1 vì ô chưa đổi; (b) "bước dừng" tính mọi bước xe ở trên ô đường kể cả bước đang rời đi.

```python
from hexudon.engine import HexudonEngine
from hexudon.models import DayInput
eng = HexudonEngine(cfg)
res = eng.simulate_day(day_input, actions, record_frames=False)
print(res.valid, res.error_message, res.chains_collected_today, res.portions_collected_today)
```

---

## 5. Chọn vai trò xe trước trận (`solver.py: select_roles`)

**Mục đích:** quyết định xe nào là tuần tra / tiếp xăng (cố định cả trận). **Đây là đòn bẩy lớn nhất đo được:** chỉ đổi vai trò, F1 một số map tăng 9→11, 14→17, 17→19.

**Giả mã:**

```
function select_roles():
    # A. ứng viên: mọi tập xe tiếp xăng kích thước 0..kmax
    kmax = min(3 if N>=7 else 2, N-1)             # luôn còn >=1 xe tuần tra
    C = { tập R ⊆ {0..N-1}, |R| ≤ kmax }
    # B. rollout rẻ (chỉ khi |C| > 12), có giới hạn thời gian role_time_s
    if |C| > 12:
        điểm(c) = quick_rollout(c, 1 cấu hình)  với c ∈ C, dừng khi hết role_time_s
        C = top 5 theo (F1,F2,F3)
    # C. rollout đầy đủ
    điểm(c) = quick_rollout(c, cả portfolio xác định);  xếp giảm dần
    # D. chơi thử bằng plan_day thật
    for c in top 3:  for seed in (seed0, 7, 99):
        (stop nếu hết role_time_s)
        điểm = play_rollout(c, seed, plan_budget_ms)
    chọn (c*, seed*) tốt nhất;  self.seed = seed*
    # E. tiến hóa hệ số ưu tiên (mục 12)
    self.spot_bias = evolve_bias(c*, evolve_time_s)
    return c*
```

**Số ứng viên (giai đoạn A):** $\sum_{k=0}^{k_{max}}\binom{N}{k}$. Ví dụ $N=4,k_{max}=2$ ⇒ $1+4+6=11$; $N=5$ ⇒ 16; $N=8,k_{max}=3$ ⇒ $1+8+28+56=93$.

**`quick_rollout`** (`_quick_rollout_roles`): chơi cả $D$ ngày; mỗi ngày dựng lịch bằng các cấu hình portfolio xác định và lấy lịch có khóa $K$ tốt nhất; cộng dồn $(|\text{chuỗi toàn trận}|,\ \sum N_{day},\ \sum P)$. Chỉ tính lưu lượng của chính mình.

**Vì sao cần giai đoạn D:** rollout rẻ xếp hạng sai ở một số map (map 39 và 105: vai trò do rollout rẻ chọn cho F1 14 và 18, trong khi vai trò khác cho 17 và 19). Chơi thử bằng bộ lập kế hoạch thật sửa được map 105.

**Chi phí:** ≈ 30–45 s trên map 32×32/8 xe. Chỉnh `role_time_s` (mỗi giai đoạn B và D, mặc định 8 s) và `evolve_time_s`.

```python
s = HexudonSolver(cfg, seed=42)
s.plan_budget_ms = 120.0; s.role_time_s = 8.0; s.evolve_time_s = 15.0
roles = s.select_roles()
print([r.value for r in roles], s.seed, len(s.spot_bias))
```
Công tắc: `HEX_OLD_ROLES=1` (cách cũ: vài tổ hợp chọn tay), `HEX_PLAYSEL=0` (bỏ D và E).

---

## 6. Bảy heuristic H1–H7 (`heuristics.py: HexudonHeuristics`)

### H1 — Độ hiếm chuỗi và độ cô lập
$$\text{scarcity}(c)=\Big(\tfrac{1}{count(c)}\Big)^{0.65},\qquad
\text{isolation}(s)=\frac{\overline{d_{hex}(s,\cdot)}}{\max_{s'}\overline{d_{hex}(s',\cdot)}}$$
Thưởng (khi chuỗi mới trong ngày): $reward \leftarrow reward\cdot\big(1+w_{sc}(0.7\,\text{scarcity}+0.3\,\text{isolation})\big)$.
*Ví dụ:* chuỗi chỉ có 1 quán ⇒ scarcity $=1$; chuỗi có 4 quán ⇒ $0.25^{0.65}\approx0.406$. Với $w_{sc}=0.35$, isolation $=0.5$: hệ số $=1+0.35(0.7\cdot1+0.3\cdot0.5)=1.2975$.

### H2 — Trường hấp dẫn cụm quán
$$\text{pot}(s)=\sum_{s'\ne s,\ d(s,s')\le10}\frac{stock(s')\cdot m(s')}{(d(s,s')+1)^{1.4}},\quad
m=\begin{cases}3.5&\text{chuỗi chưa thu toàn trận}\\2.2&\text{chưa thu hôm nay}\\1.2&\text{còn lại}\end{cases}$$
(với $m$ chỉ áp dụng khác chuỗi $s$; cùng chuỗi $m=1$). Cộng vào điểm đích: $+\,w_{grav}\cdot\text{pot}(s)$.
*Ví dụ:* quán lân cận cách 3 bước, kho 2, chuỗi chưa thu toàn trận: $2\cdot3.5/4^{1.4}=7/6.96\approx1.0$; với $w_{grav}=18$ cộng khoảng $+18$.

### H3 — Nước rút tới xe tiếp xăng
Xe tiếp xăng không tốn xăng nên luôn đi theo `apsp_steps` (đường 1 bước/ô nếu thông thoáng) để tới điểm hẹn sớm nhất. Cài trong mục 8.

### H4 — Độ trung gian đường bộ và tránh tự làm tắc
$$\text{betw}(u)=\frac{\#\{(s_i,s_j):\ u\in \text{đường ngắn nhất}(s_i\to s_j)\}}{\max_{u'}(\cdot)}$$
Cuối ngày, `_step_off_road_if_needed` đưa xe đang đứng trên ô đường sang ô đồng bằng kề (ưu tiên ô quán) **trước khi `WAIT`**, để không tạo bước đứng trên đường ⇒ hôm sau ít tắc. (Độ trung gian dùng để nhận diện nút cổ chai.)

### H5 — Giá ẩn của xăng
$$\lambda=\min\Big(1.2,\ 0.18\cdot\frac{F_{max}}{\max(1,f)}\cdot \delta\Big),\quad
\delta=\mathrm{clip}\Big(\frac{d_{tanker}}{\max(4,\,0.4(W+H))},\ 0.25,\ 1.5\Big)$$
($\delta=1.5$ nếu không có xe tiếp xăng; $f$ là xăng hiện có).
*Ví dụ:* $F_{max}=18$, $f=6$, xe tiếp xăng gần nhất cách 10 bước, $W+H=32$: $\delta=10/12.8=0.781$, $\lambda=0.18\cdot3\cdot0.781=0.42$. Khi không bật H1/H2 dùng hằng số $\lambda=0.32$.

### H6 — Đấu giá Regret-2 giữa các xe tuần tra
Với quán $s$ mới trong ngày: $a_{me}$ = bước tới của xe đang xét, $a_{oth}$ = bước tới sớm nhất của xe khác (nếu khả thi):
$$reward\leftarrow\begin{cases}0.8\cdot reward & a_{oth}+2<a_{me}\ \ (\text{xe khác tới sớm hơn hẳn})\\ reward\cdot(1+0.025\cdot\min(12,\,a_{oth}-a_{me})) & a_{oth}>a_{me}+2\ \text{và bật 2-opt}\end{cases}$$

### H7 — Ghé quán trên đường (`find_best_via_spot`)
Với đích $v$ từ $u$: tìm quán $w$ chưa ghé, còn kho, sao cho $\Delta=d(u,w)+d(w,v)-d(u,v)\le\Delta_{max}$ và vẫn đủ bước/xăng tới $v$ ($\Delta_{max}=2$ nếu $w$ mở chuỗi mới trong ngày, ngược lại $0$). Giá trị:
$$val=\begin{cases}1000&\text{chuỗi mới toàn trận}\\200&\text{mới trong ngày}\\50&\text{còn lại}\end{cases}-15\Delta-0.1\,d(u,w)$$
Chọn $w$ có $val$ lớn nhất. Không áp dụng khi $d(u,v)\le2$.

```python
from hexudon.heuristics import HexudonHeuristics
h = HexudonHeuristics(cfg, grid)
h.chain_scarcity, h.spot_isolation, h.road_betweenness            # H1, H4 (tính sẵn)
pot = h.compute_gravity_potential(steps, stocks, chains_today, chains_overall)   # H2
lam = h.compute_dynamic_fuel_shadow_price(cell, fuel, [tanker_cell], steps)      # H5
w = h.find_best_via_spot(u, v, visited, stocks, chains_today, chains_overall,
                         remaining_steps, remaining_fuel, steps, fuel)           # H7
```

---

## 7. Bộ dựng lịch tham lam một ngày (`_build_schedule`)

**Mục đích:** lõi của mọi ứng viên. Biến "ý định" thành dãy `MOVE/WAIT` hợp lệ cho từng xe.

**Giả mã (rút gọn):**
```
builders = mỗi xe: (ô, xăng, bước đã dùng, danh sách lệnh)
while còn xe tuần tra còn bước:
    pb = xe tuần tra có (bước đã dùng, id) nhỏ nhất            # xe "rảnh sớm nhất"
    λ = shadow_price(pb)                                        # H5 hoặc 0.32
    nếu có hàng đợi ép (forced_tours) hợp lệ → đích = đầu hàng đợi
    ngược lại: với mỗi quán s khả thi (kho>0, chưa ghé, đủ bước & xăng):
        tính score(s)  (công thức bên dưới);  đích = argmax score
    nếu cần tiếp xăng (không còn đích, hoặc xăng ≤ ⌊F·θ⌋ và còn ≥3 bước) → rendezvous (mục 8)
    nếu bật 2-opt: thử đảo cặp (s1,s2) và chèn quán trung gian H7
    thêm lệnh MOVE theo đường ngắn nhất tới đích; ghi nhận thu udon trên đường
cuối ngày: bước khỏi ô đường (H4); xe tiếp xăng đón xe tuần tra đúng thời điểm; WAIT cho đủ bước
```

**Điểm một đích** $s$ cho xe $pb$ (`eff` = $\max(1,\text{bước tới }s)$, $f_c$ = xăng tới $s$):

$$\boxed{score(s)=\frac{reward(s)}{eff+\lambda\,f_c+1}\;+\;w_{la}\cdot v_{next}\;+\;w_{grav}\,\text{pot}(s)\;-\;w_{cl}\cdot d(\text{neo}_{pb},s)}$$

rồi nhân nhiễu và hệ số ưu tiên:

$$score\leftarrow score\cdot\big(1+\mathcal U(-\epsilon,\epsilon)\big)\cdot \beta_{(day,s)}$$

| Ký hiệu | Ý nghĩa |
|---|---|
| $reward$ | $100 + 10^6\,[\text{chuỗi mới toàn trận}] + 15000\,[\text{chuỗi mới trong ngày}]$, rồi nhân H1, H6 |
| $\lambda$ | giá ẩn của xăng (H5) |
| $w_{la}\cdot v_{next}$ | thưởng nhìn trước: $v_{next}=\max_{s'}\frac{r'}{d(s,s')+\lambda f(s,s')+1}$, $r'=100+5\cdot10^5$ (chuỗi mới toàn trận) hoặc $+8000$ (mới trong ngày), chỉ xét $s'$ khác chuỗi $s$ |
| $w_{grav}\text{pot}(s)$ | H2 |
| $w_{cl}\,d(\text{neo},s)$ | phạt xa "neo" (ô đầu ngày của xe) để các xe chia vùng |
| $\epsilon$ | biên nhiễu (0 ở cấu hình xác định) |
| $\beta_{(day,s)}$ | hệ số ưu tiên do ES học (mục 12); mặc định 1 |

Bội số $10^6\gg15000\gg100$ bảo đảm thứ tự F1 ≫ F2 ≫ F3 ngay trong lựa chọn đích.

**Ví dụ số:** quán chuỗi mới toàn trận, 4 bước, 2 xăng, $\lambda=0.32$: $reward=1{,}015{,}100$; $score=1{,}015{,}100/(4+0.64+1)\approx 179{,}982$ (chưa tính các số hạng nhỏ). Quán chuỗi đã có, cùng khoảng cách: $reward=100$ ⇒ $score\approx17.7$ — chuỗi mới luôn thắng.

**Fallback khi thiếu xăng:** nếu đường theo `steps` không đủ xăng, thử đường theo `fuel` (`f_dist_*`); nếu vẫn không đủ thì bỏ quán đó.

**Cấu hình portfolio xác định** (`_get_deterministic_portfolio`, 6 cấu hình): các cặp (chế độ APSP, ngưỡng xăng $\theta$, $w_{cl}$, $w_{la}$) ví dụ `steps/0.35/0.15/0.30`, `balanced/0.40/0.25/0.25`, `fuel/0.30/0.10/0.35`, `steps/0.50/0.35/0.20`, `balanced/0.25/0.05/0.40`, `steps/0.35/0/0`. **Portfolio heuristic** (3 cấu hình) bật thêm H1 ($w_{sc}\in\{0.35,0.45,0.30\}$), H2 ($w_{grav}\in\{18,25,15\}$) và 2-opt.

**Độ phức tạp:** mỗi lần chọn đích $O(S)$ (hoặc $O(S^2)$ khi tính nhìn trước), $S\le45$ quán.

---

## 8. Hẹn xe tiếp xăng (`_try_schedule_rendezvous`)

**Mục đích:** khi xe tuần tra sắp cạn xăng (hoặc hết đích khả thi), chọn **xe tiếp xăng**, **ô hẹn** $m$ và **thời điểm** để nạp đầy xăng với chi phí thời gian nhỏ nhất.

Với mỗi xe tiếp xăng $rb$ và ô hẹn ứng viên $m$ (xe tuần tra $pb$ đi bằng đường `steps` nếu đủ xăng, ngược lại đường `fuel`):

$$t_{pb}=pb.step+d_{pb\to m},\quad t_{rb}=rb.step+d_{rb\to m},\quad t_{meet}=\max(t_{pb},t_{rb}),\quad t_{done}=t_{meet}+1$$

Điều kiện: $t_{done}\le max\_steps$ (cần ≥1 bước chung ô). Chi phí hiệu dụng:

$$c(m)=t_{done}-b_m,\qquad b_m=\begin{cases}3&m\text{ là quán chuỗi mới toàn trận}\\2&\text{mới trong ngày}\\1.5&\text{quán còn lại}\\0&\text{không phải quán}\end{cases}$$

Chọn $(rb,m)$ có $c$ nhỏ nhất. Sau đó: cả hai xe đi theo đường tới $m$, xe tới sớm **chờ** tới $t_{meet}$, rồi cùng `WAIT` thêm 1 bước ⇒ xe tuần tra có xăng $=F_{max}$ (và thu udon nếu $m$ là quán).

**Thu hẹp tập ô hẹn** khi bản đồ >256 ô: $\{pb.cell, rb.cell\}\cup N(pb.cell)\cup\{\text{mọi quán}\}\cup\{\text{ô trên đường } rb\to pb\}$ (nhanh gấp ~2×).

**Lỗi đã sửa (Audit 2):** trước đây xe tiếp xăng tới sớm rồi tự gán ảo "đã đổ xăng" khi xe tuần tra chưa tới; nay đồng bộ bằng $t_{meet}$.

---

## 9. Local search lộ trình (`_run_tour_local_search`, Phase 3)

Chạy trên **lộ trình quán** $\{pid: [s_1,s_2,\dots]\}$ của lịch tốt nhất; mỗi biến thể dựng lại bằng bộ dựng với `forced_tours` (2 ngưỡng xăng 0.35 và 0.45) rồi qua engine.

**Toán tử 1 — 2-opt nội bộ** (`optimize_spot_sequence_2opt`):
$$cost(\text{seq})=\sum_i d_{steps}(prev_i, s_i),\quad \text{chấp nhận đảo đoạn }[i..j]\text{ nếu }\ f(\text{seq}')\le 3F_{max}\ \text{và}\ (s'<s\ \text{hoặc}\ (s'=s\wedge f'<f))$$
Lặp tối đa 20 vòng cho tới khi không cải thiện.

**Toán tử 2 — Chèn chuỗi bị sót:** với tối đa 2 chuỗi chưa thu hôm nay (ưu tiên chưa thu toàn trận), chọn $(pid, s, pos)$ với $pos\in\{0,1,2\}$ cực tiểu hóa độ lệch

$$\Delta=d(prev,s)+d(s,next)-d(prev,next)$$

chèn rồi chạy lại 2-opt.

**Toán tử 3 — Đổi chéo giữa hai xe:** với hai xe $a,b$ và vị trí $i,j$ trong 3 vị trí đầu, hoán đổi $s_a^i\leftrightarrow s_b^j$ nếu giảm tổng bước:
$$saving=d(p_a,s_a)+d(p_b,s_b)-d(p_a,s_b)-d(p_b,s_a)>0$$

**Ví dụ 2-opt:** lộ trình $[A,B,C]$ với $d$(start,A)=6, $d$(A,B)=8, $d$(B,C)=2 ⇒ tổng 16 bước. Thử đảo đoạn $[A,B]	o[B,A]$: $d$(start,B)=4, $d$(B,A)=8, $d$(A,C)=5 ⇒ tổng 17 > 16 ⇒ **không** chấp nhận. Thử đảo $[B,C]	o[C,B]$: $d$(start,A)=6, $d$(A,C)=5, $d$(C,B)=2 ⇒ tổng 13 < 16 ⇒ chấp nhận (và kiểm tra xăng $\le 3F_{max}$).

---

## 10. ILS trên lộ trình từng xe (`_ils_tours`, Phase 3b)

**Mục đích:** biến Phase 3 (một lượt, 3 toán tử cố định) thành **tìm kiếm lặp kiểu ruin-and-recreate**, dùng chính bộ dựng tham lam cũ làm bước "recreate".

**Giả mã:**
```
(K*, tours) ← lịch tốt nhất hiện có
repeat n_iter = min(200, ngân_sách_ms / 5) lần:
    tours' ← bản sao tours
    chọn ngẫu nhiên một xe p và một phép:
        0: BỎ     một quán ngẫu nhiên khỏi lộ trình p
        1: CHÈN   một quán bất kỳ vào vị trí rẻ nhất của p (gỡ nó khỏi xe khác nếu có)
        2: CHUYỂN một quán của p sang xe q khác, vị trí rẻ nhất
        3: ĐỔI    một quán của p với một quán của q
    chạy 2-opt trên lộ trình p
    lịch ← build_schedule(forced_tours = tours')      # recreate bằng tham lam
    nếu lịch hợp lệ:  K' ← khóa(lịch)
        nếu K' ≥ K*:  chấp nhận (cho trôi ngang);  nếu K' > K*: lưu làm ứng viên mới
trả các ứng viên tốt hơn nghiêm ngặt
```
- **Vị trí chèn rẻ nhất:** $pos^*=\arg\min_{pos}\ d(prev,s)+d(s,next)-d(prev,next)$.
- Chấp nhận $\ge$ (không chỉ $>$) giúp thoát cao nguyên khi nhiều lịch cùng khóa.
- Nhiễu dùng `self.rng` đã gieo theo (seed, ngày) nên **tất định**.

**Chi phí:** mỗi vòng = 1 lần dựng lịch + 1 mô phỏng ⇒ $\approx$ 5–20 ms/vòng trên map vừa. **Hiệu quả đo:** F2 979→998, F3 1410→1430 (10 map, 400 ms); không map nào mất F1. Tắt bằng `HEX_ILS=0`.

---

## 11. Lookahead (Phase 4)

**Mục đích:** hôm nay ăn tham có thể làm cạn xăng hoặc đỗ sai chỗ cho ngày mai. Phase 4 chấm các **trạng thái cuối ngày khác nhau** bằng cách chơi thử tương lai.

**Bản 1 ngày (cũ):** với tối đa 4 ứng viên khác nhau về (vị trí, xăng) cuối ngày, chơi thử ngày $d+1$ bằng 3 cấu hình xác định (đường giả định như hôm nay), khóa 2 ngày:
$$K_2=(N_{new}^{(d)},\ N_{day}^{(d)},\ |\text{chuỗi toàn trận sau }d{+}1|,\ N_{day}^{(d)}+N_{day}^{(d+1)},\ P^{(d)}+P^{(d+1)}+\lfloor \Phi^{(d+1)}/3\rfloor,\dots)$$

**Bản nhìn xa cả trận (mới):** với mỗi ứng viên, chơi nốt mọi ngày $d+1..D$ bằng 2 cấu hình rẻ; đường tính từ **chính lưu lượng của mình** (`compute_road_states([stays], 2)`):

$$K_{H}=\Big(\ |\text{chuỗi toàn trận cuối}|,\ \sum_{d'\ge d}N_{day}^{(d')},\ \sum_{d'\ge d}P^{(d')},\ \Phi,\ \Pi,\ B\Big)$$

Chọn ứng viên có $K_H$ lớn nhất. Số ứng viên đánh giá: $\max(2,\lfloor \text{ngân sách}/100\rfloor)$.

**Khi nào bật nhìn xa:** chỉ khi **F1 chưa đủ chuỗi** hoặc ngân sách ≥1500 ms (đắt 3–5× thời gian, lợi nhiều trên map ít xe: map 39 F1 14→17/18). `HEX_HORIZON=0` ép dùng bản 1 ngày.

---

## 12. Tiến hóa hệ số ưu tiên (1+1)-ES (`_evolve_bias`)

**Mục đích:** bộ dựng tham lam từng ngày không thấy được "ngày nào nên lấy quán nào để cả trận tốt". ES học điều đó trên **cả trận**.

**Biểu diễn:** $\beta:\ (day,\,spot)\mapsto[0.1,\,10]$, mặc định 1; nhân vào $score$ của quán đó vào ngày đó (mục 7).

**Giả mã:**
```
β ← {};  best ← play(roles, β, plan_budget_ms)               # fitness = (F1, F2, F3)
while thời gian < evolve_time_s:
    β' ← β
    lặp 1..3 lần: chọn (d, s) ngẫu nhiên;  β'[d,s] ← clip(β'[d,s] · x, 0.1, 10),  x ∈ {0.25, 0.5, 2, 4}
    f' ← play(roles, β', plan_budget_ms)
    nếu f' ≥ best:  β ← β';  best ← f'                        # chấp nhận bằng (trôi ngang)
# kiểm chứng cuối
nếu play(roles, β) > play(roles, {}) nghiêm ngặt thì trả β, ngược lại trả {}
```
**Quan trọng (phát hiện từ thực nghiệm):** tinh chỉnh ở ngân sách rẻ (30 ms/ngày) **không** chuyển sang ngân sách thật; fitness phải đo ở **ngân sách thật** (`plan_budget_ms`). Trên map 39: tune rẻ ⇒ 0 hệ số được giữ; tune ở ngân sách thật ⇒ F2 28→33, F3 29→35.

**Fitness** là so sánh từ điển $(F_1,F_2,F_3)$ của `_play_rollout_roles`. **Hiệu quả đo:** F3 1882→1918 trên 13 map. Tăng thời gian từ 15 s lên 60 s **không** giúp thêm (bão hòa). Tắt bằng `HEX_ES=0`, đổi thời gian bằng `HEX_ES_TIME=<giây>` hoặc `solver.evolve_time_s`.

```python
roles = s.select_roles()          # đã gồm ES ở cuối
print(s.spot_bias)                # {(ngày, ô quán): hệ số}
bias = s._evolve_bias(roles, 30.0)   # chạy riêng ES 30 giây
```

---

## 13. Tính tất định và chơi thử (`plan_day`, `_play_rollout_roles`)

- Đầu `plan_day`: `self.rng = Random(seed*1000 + ngày)`. Các vòng lặp dùng **số lần lặp**, không dùng đồng hồ:
  - số rollout ngẫu nhiên $=\min(600,\lfloor \text{ngân sách}/15\rfloor)$;
  - local search chỉ chạy khi ngân sách ≥ 60 ms;
  - số ứng viên lookahead $=\max(2,\lfloor\text{ngân sách}/100\rfloor)$.
- Vì thế cùng (seed, trạng thái, ngân sách) luôn cho cùng lịch ⇒ **kết quả chơi thử trước trận được tái hiện đúng trong trận** khi chỉ có 1 đội. Đây là cơ sở để chọn (vai trò, seed) và ES.
- Khi có đối thủ, đường bị họ làm đổi ⇒ quỹ đạo lệch dần so với lúc chơi thử (hạn chế, mục 17).

---

## 14. Đấu trường đối thủ mẫu (`arena.py`)

`MultiTeamArena.run_tournament` chạy nhiều đội cùng lúc trên một map, **chia sẻ lưu lượng đường** (đúng luật: tổng bước đứng của mọi đội chia số đội). Đối thủ:
1. **Greedy Dijkstra Orienteering:** mỗi xe chọn quán gần nhất còn thu được.
2. **Chain-Auction + Gravity:** đấu giá chuỗi giữa các xe, thêm trường hấp dẫn.
3. **Voronoi + TSP 2-opt:** chia bản đồ theo Voronoi, mỗi xe giải TSP trong vùng rồi 2-opt.

```bash
python run_benchmark.py       # PHẦN 2 in bảng xếp hạng 4 đội trên 4 kịch bản
```

---

## 15. Gửi đáp án lên server (`client.py`)

- `MatchRunner.run_match(time_budget_ms_per_day)`: chạy trận nội bộ, ghi replay; đặt `solver.plan_budget_ms` bằng ngân sách mỗi ngày trước khi `select_roles`.
- `ContestApiClient`: `get_map_config`, `submit_roles`, `submit_day_actions`, `plan_and_submit_dual_commit`.

**Dual-Commit hiện tại:** gửi lần 1 với ngân sách 15 ms, tìm sâu tiếp (500 ms), chỉ gửi lại nếu $(F_1,F_2,F_3)$ **lớn hơn hẳn**.

> **Cảnh báo đã đối chiếu với đề:**
> 1. Đề tính F4 theo **câu trả lời hợp lệ cuối cùng được chấp nhận**, nên gửi lại làm thời gian bị tính theo **lần gửi sau**. Chú thích "khóa F4 bằng lần gửi đầu" trong mã là **sai**.
> 2. Đề cảnh báo gửi quá nhiều câu trả lời có thể bị coi là gây rối và bị loại (không nêu ngưỡng).
> 3. Endpoint và schema JSON chỉ là phỏng đoán cho tới khi BTC công bố.
> 4. `plan_and_submit_dual_commit` dùng ngân sách 15/500 ms, **khác** `plan_budget_ms` mà ES đã tinh chỉnh; hệ số $\beta$ vẫn áp dụng nhưng không còn được kiểm chứng đúng ngân sách. Khi chốt giới hạn thời gian của BTC nên đặt `plan_budget_ms` bằng đúng ngân sách dùng khi nộp.

---

## 16. Bảng tham số và công tắc môi trường

| Tham số (thuộc tính `solver`) | Mặc định | Ý nghĩa |
|---|---|---|
| `seed` | 42 | seed cơ sở; được ghi đè bởi giai đoạn D |
| `plan_budget_ms` | 120 | ngân sách mỗi ngày dùng khi chơi thử/ES |
| `role_time_s` | 8.0 | giới hạn thời gian mỗi giai đoạn B và D |
| `evolve_time_s` | 15.0 | thời gian ES |
| `spot_bias` | `{}` | hệ số $\beta_{(day,s)}$ do ES học |

| Biến môi trường | Tác dụng |
|---|---|
| `HEX_OLD_ROLES=1` | chọn vai trò theo cách cũ (không tìm kiếm rộng) |
| `HEX_PLAYSEL=0` | bỏ chơi thử (D) và ES (E) |
| `HEX_ES=0` | tắt ES |
| `HEX_ES_TIME=<giây>` | đổi thời gian ES |
| `HEX_ILS=0` | tắt ILS lộ trình |
| `HEX_HORIZON=0` | luôn dùng lookahead 1 ngày |
| `HEX_SEED=<n>` | seed cơ sở trong `bench_wide.py` |

**Mẫu A/B một thuật toán** (ví dụ ILS, 10 map, ngân sách 400 ms, tắt các thuật toán khác để cô lập):

```bash
for i in 0 1; do
  HEX_ILS=$i HEX_ES=0 HEX_PLAYSEL=0 HEX_HORIZON=0 \
  python bench_wide.py 0 400 39,13,5,1,0,3,12,4,15,105 | tail -1
done
```

---

## 17. Hạn chế đã biết
- Tính tất định chỉ đúng khi **1 đội**; đối thủ làm đổi tình trạng đường ⇒ lệch dần so với lúc chơi thử.
- Chọn vai trò + ES tốn 30–45 s trước trận trên map lớn; phải chỉnh theo thời gian BTC cho.
- Map ít xe, ít ngày vẫn có thể thiếu chuỗi (map 39: 17–18/20).
- Thêm thời gian hoặc rollout ngẫu nhiên không cải thiện thêm (đã đo): muốn mạnh hơn cần toán tử tìm kiếm mới.
- Hai giả định luật (mục 4) và toàn bộ tham số thật của BTC (số đội, ngưỡng đường, thời gian, schema API) chưa được xác minh.
