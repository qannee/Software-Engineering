# QUẬN 1 TOURISM

Ứng dụng hướng dẫn du lịch dạng PWA cho Quận 1. Frontend dùng React/Vite; API dùng FastAPI; dữ liệu có thể chạy demo trong bộ nhớ hoặc lưu bằng PostgreSQL cài trực tiếp trên máy. Dự án không cần Docker.

## Cách chạy nhanh trong VS Code

### Cài một lần

Cài Python 3.11 trở lên và Node.js 18 trở lên, sau đó mở thư mục dự án trong VS Code. Mở Terminal tại thư mục dự án và chạy:

```powershell
py -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
cd frontend
npm install
cd ..
```

Nếu PowerShell chặn kích hoạt môi trường, bỏ qua lệnh `Activate.ps1`; những lệnh khởi động bên dưới gọi Python trong `.venv` trực tiếp.

### Khởi động

Cách dễ nhất: trong VS Code chọn **Terminal → Run Task → QUAN 1 TOURISM: Start Full App** (hoặc nhấn `Ctrl+Shift+B`), chờ hai terminal báo đã chạy rồi mở <http://localhost:5173>.

Nếu task của VS Code không chạy được, mở hai terminal tại thư mục dự án:

Terminal 1 — backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Terminal 2 — frontend:

```powershell
cd frontend
npm run dev
```

Trang web: <http://localhost:5173> · API: <http://localhost:8000/docs> · Trạng thái API: <http://localhost:8000/health/ready>.

Trang chính <http://localhost:5173> yêu cầu đăng nhập tài khoản khách; có thể tạo tài khoản ngay trên trang. Mỗi tài khoản có danh sách yêu thích riêng được lưu ở backend. Trang đăng nhập quản trị có địa chỉ riêng <http://localhost:5173/admin> (cũng có thể bấm **Quản trị** trong ứng dụng) và chỉ nhận tài khoản Admin/Reviewer. Ở chế độ demo mặc định, tài khoản quản trị là `admin` / `quan1-demo`. Hãy đổi mật khẩu và `JWT_SECRET` trong `backend/.env` nếu dùng dữ liệu thật hoặc mở ứng dụng ra mạng.

## Dùng PostgreSQL

Ứng dụng khởi động được ngay ở chế độ demo không cần PostgreSQL. Chế độ demo lưu dữ liệu trong bộ nhớ nên POI, tài khoản mới, bản nháp và analytics sẽ mất khi tắt backend. Muốn lưu lâu dài, cài PostgreSQL trực tiếp trên máy rồi tạo database:

```powershell
psql -U postgres -c "CREATE DATABASE quan1_tourism;"
```

Sao chép `backend/.env.example` thành `backend/.env`, sửa cấu hình:

```dotenv
POSTGRES_ENABLED=true
DATABASE_URL=postgresql+psycopg://postgres:MAT_KHAU_CUA_BAN@localhost:5432/quan1_tourism
REDIS_ENABLED=false
ADMIN_USERNAME=admin
ADMIN_PASSWORD=MAT_KHAU_MOI
JWT_SECRET=CHUOI_NGAU_NHIEN_DAI_VA_RIENG
```

Khởi động lại backend. Ứng dụng tự tạo các bảng và nạp địa điểm mẫu một lần khi database còn trống. Không đưa mật khẩu hoặc khóa API thật lên Git.

Schema PostgreSQL được quản lý bằng Alembic trong `backend/migrations`. Khi bật PostgreSQL, backend áp dụng migration trước khi khởi động API; có thể chạy thủ công từ thư mục `backend` bằng `..\.venv\Scripts\alembic.exe upgrade head`. Migration hiện tại tạo các bảng còn thiếu và thêm ràng buộc cho tọa độ, bán kính geofence, trạng thái, vai trò, ngôn ngữ, số lần thử tác vụ và loại sự kiện. Nếu database cũ có dữ liệu vi phạm các ràng buộc mới, migration sẽ dừng để dữ liệu được rà soát thay vì tự sửa âm thầm.

Redis là tùy chọn khi phát triển local. Để chạy worker nền phân tán, cài Redis trực tiếp hoặc dùng một dịch vụ Redis, rồi đặt `REDIS_ENABLED=true` và `REDIS_URL` trong `backend/.env`. Chạy API như thường lệ và mở thêm terminal tại `backend`:

```powershell
.\.venv\Scripts\python.exe -m arq app.worker.WorkerSettings
```

Worker cần PostgreSQL và Redis cùng hoạt động. Khi bật Redis, API ghi tác vụ vào PostgreSQL/outbox rồi worker xử lý; migration tự đưa các tác vụ còn dang dở của schema cũ trở lại hàng đợi. Chế độ local mặc định không cần Redis và vẫn chạy tác vụ trong API.

## Tính năng

- Khám phá POI trên bản đồ tương tác, xem khoảng cách và dùng GPS để kích hoạt geofence/thuyết minh tự động. Vị trí được xử lý trên thiết bị, không gửi vào analytics.
- Nội dung tiếng Việt/Anh, phát audio đã tạo hoặc dùng speech synthesis của trình duyệt.
- Đăng ký/đăng nhập tài khoản khách, đăng xuất và đồng bộ địa điểm yêu thích theo từng tài khoản; quản trị ở đường dẫn `/admin` riêng.
- Mỗi lượt thuyết minh tự dừng sau tối đa 1 phút. GPS yêu cầu người dùng cấp quyền cho trình duyệt và HTTPS hoặc localhost.
- 20 POI mẫu có tọa độ, vùng geofence, mô tả song ngữ và nguồn tham khảo; backend và fallback frontend dùng chung dữ liệu xuất từ `backend/app/repositories/poi_repository.py`. Sau khi sửa seed, chạy `backend\.venv\Scripts\python.exe scripts\export_demo_pois.py` để cập nhật fallback.
- Gói ngoại tuyến lưu POI, bản dịch và audio. Có thể lưu thêm tile bản đồ cho vùng POI ở zoom 12–16 bằng provider đã cấp quyền tải/lưu offline; ứng dụng tiếp tục tải phần còn thiếu nếu người dùng thử lại. Cần cấu hình `VITE_MAP_TILE_URL`, `VITE_MAP_ATTRIBUTION` và tăng `VITE_MAP_VERSION` trong `frontend/.env.local` khi thay đổi bộ tile; provider phải cho phép CORS để trình duyệt đọc và lưu tile. Khi không cấu hình provider, bản đồ trực tuyến vẫn dùng OpenStreetMap và ứng dụng chỉ lưu nội dung/audio.
- Quản trị POI, tọa độ và bán kính geofence; cấu hình liên kết Wikipedia.
- Pipeline Wikipedia → tạo bản nháp AI/trích xuất dự phòng → reviewer chỉnh sửa và duyệt → dịch tiếng Anh → TTS hai ngôn ngữ → xuất bản/gỡ xuất bản.
- Theo dõi task, thử lại lỗi tạm thời, khôi phục task đang chờ khi backend khởi động lại.
- Đăng nhập JWT và đăng xuất có thu hồi token phía server; ghi nhật ký đăng nhập thành công/thất bại, đăng xuất và thao tác quản trị. Admin xem nhật ký trong tab **Nhật ký hoạt động**. Hệ thống không ghi mật khẩu vào log.
- Vai trò Admin/Reviewer, quản lý tài khoản và analytics chỉ ghi sau khi khách cấp consent.
- Người dùng có thể thu hồi consent; sự kiện gắn với consent đó sẽ bị xóa. Worker giữ số liệu chi tiết tối đa 90 ngày và tạo bản tổng hợp 30 ngày cho dashboard quản trị.

## Dịch vụ nội dung tùy chọn

Trang quản trị và luồng biên tập dùng được mà không cần khóa dịch vụ ngoài. Khi thiếu AI key, hệ thống tạo bản nháp bằng cách trích nội dung nguồn để reviewer biên tập. Có thể tự nhập bản dịch tiếng Anh. Muốn tự động hóa AI, dịch và audio, điền các khóa/voice ID trong `backend/.env` (xem `backend/.env.example`) rồi khởi động lại backend. Nội dung luôn phải qua bước duyệt trước khi xuất bản.

Frontend có thể trỏ API khác bằng `VITE_API_URL` trong `frontend/.env.local`.

## Kiểm tra CI và cấu hình production

GitHub Actions chạy kiểm tra cú pháp và test API, test geofence, kiểm tra tài nguyên PWA, sau đó build frontend và lưu `dist` thành artifact. Workflow worker có thể chạy riêng bằng lệnh ARQ ở trên. CI hiện chưa tự triển khai lên staging/hosting vì repository chưa khai báo nền tảng deploy và thông tin xác thực.

Khi đưa lên môi trường production:

1. Dùng PostgreSQL và Redis thật, đặt `APP_ENV=production`, `POSTGRES_ENABLED=true`, `REDIS_ENABLED=true`, `REDIS_URL` dùng TLS của nhà cung cấp, mật khẩu admin riêng và `JWT_SECRET` ngẫu nhiên tối thiểu 32 ký tự trong `backend/.env`.
2. Cấu hình `CORS_ORIGINS` thành danh sách domain HTTPS của frontend, phân cách bằng dấu phẩy.
3. Nếu frontend và API dùng chung domain qua reverse proxy, build frontend mặc định gọi `/api/v1`. Nếu API ở domain khác, tạo `frontend/.env.production` với `VITE_API_URL=https://api.ten-mien-cua-ban/api/v1` trước khi build. Với hai domain khác site, đặt `REFRESH_COOKIE_SAMESITE=none` để trình duyệt gửi refresh cookie; production luôn yêu cầu HTTPS.
4. Phục vụ frontend qua HTTPS để trình duyệt cho phép cài PWA và dùng GPS. Cấu hình hosting trả `index.html` cho đường dẫn ứng dụng `/admin` để URL quản trị mở trực tiếp và khi tải lại trang. PWA hỗ trợ cài trên trình duyệt tương thích; vị trí chỉ theo dõi khi người dùng mở app, chưa chạy nền như ứng dụng native.
5. Chạy ít nhất một tiến trình API và một tiến trình `arq app.worker.WorkerSettings`; cấu hình reverse proxy/giám sát để kiểm tra `/health/ready` và thu thập `/metrics`. Endpoint metrics chỉ chứa số liệu HTTP tổng hợp; giới hạn truy cập bằng firewall hoặc proxy nội bộ.
6. Tạo backup thủ công từ thư mục dự án bằng `powershell -ExecutionPolicy Bypass -File scripts\backup_postgres.ps1`. Script đọc `DATABASE_URL`/`AUDIO_DIRECTORY` từ `backend/.env`, tạo dump PostgreSQL và bản sao audio, rồi giữ 30 ngày gần nhất. Đưa lệnh này vào Windows Task Scheduler theo lịch hằng ngày; cài PostgreSQL client để có `pg_dump` trong `PATH`.
7. Kiểm thử khôi phục định kỳ vào database trống bằng `pg_restore --no-owner --dbname <database_moi> <file.dump>` và giải nén `audio-*.zip` về thư mục audio tương ứng. CI chưa có thông tin xác thực/hosting để tạo staging, backup schedule hoặc tự khôi phục.

Danh sách yêu thích đồng bộ theo tài khoản khi PostgreSQL được bật; ở chế độ demo không PostgreSQL, tài khoản và yêu thích chỉ tồn tại trong bộ nhớ backend. GPS chỉ hoạt động khi ứng dụng đang mở, trang chạy trên HTTPS hoặc localhost và người dùng cấp quyền vị trí. Trình duyệt có thể chặn tự phát audio trước khi người dùng chạm nút nghe.
