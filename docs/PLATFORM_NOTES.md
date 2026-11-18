# Nền tảng thi đấu chính thức (từ Techinical_Presentation.pptx và OpenAPI công khai)

Nguồn: file thuyết trình kỹ thuật của BTC và `GET /openapi.json` của server (công khai).
**Không lưu mật khẩu hay API key trong repo.**

## Địa chỉ
- Website: https://hexudon.hairbui76.id.vn/ · API docs (Swagger): https://hexudon.hairbui76.id.vn/docs
- Đăng nhập bằng tên đội; lấy API key bằng biểu tượng 🔑 trên website. Token gắn với đội.

## Hai loại trận
- **Active:** thi chính thức, API `Play`, tính giờ tự động theo thiết lập BTC.
- **Practice:** tự luyện, API `Practice`; mỗi game có một bản riêng cho từng đội (game id dạng `game_id:team_id`; với token đội chỉ cần truyền `game_id` trần ở `/board`).

## Quy trình gọi API
| Bước | Chính thức | Luyện tập |
|---|---|---|
| Lấy đề | `GET /api/game/config?game_id=` | `GET /api/game/config?game_id=<game_id>:<team_id>` |
| Chọn loại xe | `POST /api/game/agent-types` body `{game_id, types:[int]}` | giống |
| Lấy đề từng ngày | `GET /api/game/day?game_id=` (vị trí, xăng, giao thông, hạn nộp) | giống |
| Gửi lộ trình | `POST /api/game/actions` body `{game_id, day, actions:[[int]]}` | `POST /api/game/practice/actions` cùng body |

Khác: `GET /api/game/board` (cấu hình bản đồ, trước khi trận mở trả 409), `GET /api/game/result` (xếp hạng), `GET /api/game/replay`, `POST /api/game/practice/reset` (chơi lại luyện tập), `GET /api/game/practice/score`.

## Thông số trận (từ `GameInitRequest`, do BTC đặt khi tạo trận)
- `daySeconds[]`: **thời gian phản hồi từng ngày** (giây). · `daySteps[]`: số bước từng ngày.
- `agent_selection_time_limit`: **thời gian chọn loại xe**, mặc định **60 s** (tối đa 3600).
- `fuelLimits`, `busyThreshold` (ngưỡng đông), `jammedThreshold` (ngưỡng tắc), `players`, danh sách `teams` (mỗi đội có `agents`), `spots[]` = `{brand, pos, stocks}`.

## Định dạng chính thức (schema.pdf, KOSEN)
- **Cấu hình trước trận:** `startsAt`, `daySeconds[]` (giây trả lời mỗi ngày), `daySteps[]` (số bước mỗi ngày; số phần tử = số ngày), `map{height,width,cells[][]}` với mã địa hình **0 Đồng bằng, 1 Đường, 2 Núi, 3 Ao**, `spots[{brand,pos,stocks}]`, `agents[]` (ô xuất phát, theo thứ tự cố định), `fuelLimits`, `players` (số đội), `busyThreshold`, `jammedThreshold`. Ví dụ trong tài liệu: `daySeconds=[5,5,5,10]`, `daySteps=[50,100,150,200]`.
- **Đầu mỗi ngày:** `endsAt` (UNIX), `day` (số ngày đã xong, ngày đầu = 0), `agents[{kind,pos,fuel}]` (kind 0 tuần tra, 1 tiếp xăng), `others[{id,agents[]}]` (vị trí và xăng của đội khác), `traffics[{pos,status}]` (0 thông thoáng, 1 đông, 2 tắc). **Server không gửi số chuỗi đã thu**: client phải tự theo dõi bằng mô phỏng kế hoạch đã gửi.
- **Loại xe:** mảng `[0|1,...]` đúng số xe; sai định dạng bị từ chối; hết giờ mà chưa có bản hợp lệ ⇒ tất cả là xe tuần tra.
- **Hành động:** mỗi xe một mảng số nguyên: `0..5` = hướng di chuyển (0 trên-trái, 1 trên-phải, rồi theo chiều kim đồng hồ: 2 phải, 3 dưới-phải, 4 dưới-trái, 5 trái), `≤ -1` = chờ `|x|` bước. Tổng số bước phải khớp số bước của ngày. **Một xe sai thì toàn bộ kế hoạch của cả đội bị loại**; hết giờ mà chưa có bản hợp lệ ⇒ tất cả xe chờ cả ngày.

Đã cài đặt trong `hexudon/protocol.py` (có test `tests/test_protocol.py` dùng đúng ví dụ trong tài liệu) và `run_online.py`.

## Hệ quả cho bộ giải
1. **Số bước mỗi ngày lớn hơn nhiều so với benchmark cũ** (ví dụ 50–200, không phải 24–42). Ở chế độ này F1 và F2 gần như đạt trần; **F3 (số phần) và thời gian là chỗ phân thắng bại**. `experiments/bench_wide.py` có `HEX_STEPS=50,200` để đo đúng chế độ này.
2. **Thời gian chọn vai trò mặc định 60 s** (`agent_selection_time_limit`) và **thời gian mỗi ngày chỉ vài giây** (ví dụ 5 s, gồm cả mạng) ⇒ `run_online.py` giới hạn chọn vai trò ~25 s, ES ~8 s, ngân sách mỗi ngày ≈ 35% `daySeconds`, và luôn gửi ngay một kế hoạch nhanh hợp lệ trước khi tìm sâu.
3. Giá trị `day` trong body `POST /actions` chưa rõ (đánh số từ 0 hay 1): `run_online.py` thử `day+1` rồi `day` và nhớ giá trị được chấp nhận. **Nên thử trên Practice trước.**
4. Mapping: `fuelLimits→max_fuel`, `busyThreshold→congested_threshold`, `jammedThreshold→jam_threshold`, `players→num_teams`, `brand→chain_id`, `stocks→max_stock`.
