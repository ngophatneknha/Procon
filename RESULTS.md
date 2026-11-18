# Kết quả thử nghiệm & phương án (cập nhật 2026-11-18)

Máy giả lập tự dựng (chưa có API/BTC thật). Mọi số liệu dưới đây là trên map sinh ngẫu nhiên từ `generator.py`, 1 đội, 120 ms/ngày, chạy bằng `bench_wide.py` (2 tiến trình).

## 1. Đối chiếu PDF với handoff
- Khớp: Bảng 1, hình học even-r, kho riêng từng đội, xăng không hồi qua ngày, thứ tự 4 tiêu chí.
- SAI trong handoff: "gửi sớm 15 ms khóa F4". Đề tính F4 theo **câu trả lời hợp lệ cuối cùng** → gửi lại thì thời gian bị tính theo lần gửi sau.
- Đề không nói rõ: ngưỡng gửi lại tối đa (cảnh báo bị loại nếu quá nhiều), "bước dừng" tính lưu lượng gồm những gì, dãy lệnh thiếu bước có invalid không (an toàn: luôn WAIT cho đủ), Hình 4 không có trong PDF.

## 2. Thí nghiệm
| # | Thí nghiệm | Kết quả |
|---|---|---|
| 1 | Baseline `run_benchmark.py` | Khớp handoff: F1 đủ chuỗi 4/4 kịch bản; 8/8 test pass |
| 2 | 48 map ngẫu nhiên, ngân sách 120 / 500 / 2500 ms | F1 đủ chuỗi 45/48 ở cả 3 mức. 500 vs 120 ms: thắng 30, thua 8 (lexi). 2500 ms không hơn 500 ms → tăng thời gian chỉ có lợi tới ~500 ms |
| 3 | 3 map F1 thiếu: thử MỌI tập xe tiếp xăng (`exp_roles.py`) | F1: 9→11, 14→17, 17→19. **Chọn vai trò là đòn bẩy lớn nhất**: bản cũ chỉ thử vài tổ hợp |
| 4 | Sửa `select_roles`: thử mọi tập ≤2 (≤3 nếu N≥7) xe tiếp xăng, 2 giai đoạn (rollout rẻ → top 8 rollout đầy đủ), giới hạn 20 s | 12 map khó+thường: F1 đủ chuỗi **9/12 → 11/12**, F2 1054 → 1088, F3 1853 → 1856 |
| 5 | Giai đoạn 3: chơi thử top 3 vai trò bằng `plan_day` thật | Không cải thiện (F2 TB 701 vs 703, nằm trong nhiễu) → đã gỡ |
| 6 | Phase 4 nhìn xa hết trận (chơi nốt các ngày còn lại bằng 2 cấu hình rẻ) thay vì 1 ngày, 600 ms, 12 map | F1 đủ 11/12 (không đổi), F2 1088→1095, F3 1878→1882; map 39 F1 14→17 nhưng nhiều map lẫn lộn trong nhiễu; thời gian tăng 3–5 lần. → chỉ bật khi ngân sách ≥1500 ms/ngày |
| 7 | Horizon lookahead chỉ khi F1 chưa đủ chuỗi (hoặc ngân sách ≥1500 ms), 300 ms, 12 map | F1 đủ 11/12 (không đổi), F3 1824→1835; map 39 F1 14→17; chi phí thêm nhỏ (map 13 mất ~0.6 s/ngày) |
| 8 | Quét hợp lệ 24 map mới (id 100–123, 100 ms) | 0 lỗi/invalid; F1 đủ 23/24 (map 105 thiếu 1 chuỗi do chọn vai trò sai: quick-rollout xếp hạng sai) |
| 9 | `plan_day` tất định theo (seed, ngày) (đếm vòng lặp thay vì đồng hồ) + chọn (vai trò, seed) tốt nhất bằng chơi thử top 3 vai trò × 3 seed | 13 map, 120 ms: F1 đủ **11/13 → 12/13** (map 105 sửa được), F2 1118→1136, F3 1871→1914. Chọn vai trò tối đa ~30 s trên map 32x32/8 xe (`role_time_s`=8 s mỗi giai đoạn, chỉnh được) |
| 10 | (1+1)-ES tiến hóa hệ số ưu tiên (ngày, quán) cho bộ dựng lịch tham lam; fitness = chơi cả trận ở ngân sách thật; chỉ giữ nếu kiểm chứng tốt hơn (`evolve_time_s`=15 s, `HEX_ES=0` để tắt). Tune ở ngân sách rẻ (30 ms) KHÔNG chuyển sang ngân sách thật → phải đánh giá ở ngân sách thật | 13 map, 120 ms: F1 đủ 12/13, F2 1132→1134, F3 **1882→1918**; map 39 F1 16→17 |
| 11 | Tăng ES từ 15 s lên 60 s; tăng số rollout ngẫu nhiên 28→600 và ngân sách 120→1000 ms | Không cải thiện (F2 +8, F3 −20 / F2 +8, F3 −15, trong nhiễu) → thêm thời gian/rollout ngẫu nhiên KHÔNG giúp; cần toán tử tìm kiếm tốt hơn |
| 12 | ILS trên lộ trình từng xe (`_ils_tours`: bỏ/chèn/chuyển/đổi chéo quán, 2-opt, dựng lại bằng builder tham lam; tắt bằng `HEX_ILS=0`), 400 ms, 10 map, tắt ES/PLAYSEL để cô lập | F2 979→998, F3 1410→1430, không map nào tụt F1 |
| 13 | Tất cả bật cùng nhau (roles + seed + horizon + ES + ILS), 120 ms, 13 map | F1 đủ 12/13, F2 1136, F3 **1941** (so 1882 trước ES); map 39 F1 18/20 |

## 3. Còn tồn tại
- Map 39 (29x29, 20 chuỗi, 4 ngày, 2 xe tuần tra): F1 chỉ 14–17/20, dao động giữa các lần chạy → bộ lập kế hoạch từng ngày yếu khi ít xe/ít ngày; cần lập kế hoạch phủ chuỗi nhiều ngày.
- Chọn vai trò mất 10–47 s trước trận; chưa biết BTC cho bao nhiêu thời gian chuẩn bị.
- Tất định chỉ đúng khi 1 đội; đối thủ làm đổi đường thì quỹ đạo lệch dần so với lúc chơi thử.
- Lookahead ngày d+1 giả định đường giống hôm nay.
- Client API chỉ là phỏng đoán; cần schema thật.

## 4. Việc nên làm tiếp (ưu tiên)
1. Lập kế hoạch phủ chuỗi nhiều ngày (F1) cho map ít xe/ít ngày.
2. Giới hạn thời gian chọn vai trò theo thông báo BTC; chạy song song nếu được.
3. Dùng gần hết thời gian/ngày (≥500 ms) vì F4 chỉ xét khi hòa F1–F3; gửi 1 lần gần hạn, hoặc tối đa 2 lần.
4. Khi có hướng dẫn cuối: cập nhật `client.py`, số đội, ngưỡng đường.

## 5. Ghi chú vận hành
- Dùng tối đa 2 tiến trình (8 tiến trình đã làm tràn RAM).
- `HEX_OLD_ROLES=1` bật lại cách chọn vai trò cũ để so A/B.

## Thí nghiệm 14 — chạy thật trên server Practice (Q1, 5 xe thật)
- Lệnh: `run_online.py --practice --select-seconds 7` (token qua biến môi trường). Chọn vai trò 8.7 s: `P P R P P`; 2000 ms/ngày.
- Server: **F1 = 32/32, F2 = 288, F3 = 332** (trước đó 32 / 273 / 290). Khớp tuyệt đối với mô phỏng phía client ⇒ bộ mô phỏng đúng luật.
- `day` trong body POST: server chấp nhận thử `d+1` bị 409 ("submit day 1 before day 2"), rồi `d+0` được nhận; client tự nhớ.
- Đọc kết quả: `GET /api/game/result?game_id=<id>:83` hoặc `/api/game/practice/score` → `distinct_types`=F1, `cumulative_daily_types`=F2, `total_servings`=F3, `cumulative_response_time`=F4.
- Mô phỏng Q1–Q5 (800 ms): F2 294/319/312/301/307, F3 339/433/363/346/358.
