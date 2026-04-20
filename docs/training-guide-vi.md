# ORT Web — Tài Liệu Hướng Dẫn Sử Dụng

> **Phiên bản:** 0.3.0 | **Đối tượng:** Đội phát triển, Bộ phận kiểm soát tuân thủ, Kỹ sư vận hành

---

## Mục Lục

1. [ORT Web là gì?](#1-ort-web-là-gì)
2. [Yêu cầu hệ thống](#2-yêu-cầu-hệ-thống)
3. [Cài đặt và khởi chạy lần đầu](#3-cài-đặt-và-khởi-chạy-lần-đầu)
4. [Giao diện tổng quan](#4-giao-diện-tổng-quan)
5. [Cài đặt ORT](#5-cài-đặt-ort)
6. [Quét một dự án](#6-quét-một-dự-án)
7. [Đọc hiểu kết quả quét](#7-đọc-hiểu-kết-quả-quét)
8. [Lịch sử quét và tìm kiếm](#8-lịch-sử-quét-và-tìm-kiếm)
9. [Xem và tải báo cáo](#9-xem-và-tải-báo-cáo)
10. [Đổi ngôn ngữ giao diện](#10-đổi-ngôn-ngữ-giao-diện)
11. [Cập nhật ORT Web](#11-cập-nhật-ort-web)
12. [Xử lý các lỗi thường gặp](#12-xử-lý-các-lỗi-thường-gặp)
13. [Câu hỏi thường gặp](#13-câu-hỏi-thường-gặp)

---

## 1. ORT Web là gì?

**ORT Web** là giao diện web chạy trên máy cục bộ, được xây dựng để giúp các đội phát triển dễ dàng sử dụng công cụ **OSS Review Toolkit (ORT)** — một công cụ kiểm tra giấy phép và bảo mật mã nguồn mở được nhiều doanh nghiệp lớn áp dụng.

Thay vì phải gõ lệnh trực tiếp trên terminal, người dùng chỉ cần thao tác trên trình duyệt: chọn thư mục dự án, nhấn nút, theo dõi tiến trình và xem kết quả báo cáo.

### Vì sao cần ORT Web?

| Vấn đề thực tế | ORT Web giải quyết thế nào |
|----------------|---------------------------|
| ORT chỉ dùng được qua dòng lệnh | Giao diện web trực quan, không cần biết CLI |
| Cài đặt ORT phức tạp, nhiều bước thủ công | Cài tự động, chỉ cần một cú nhấp |
| Không biết quét đang chạy đến đâu | Log hiển thị trực tiếp theo thời gian thực |
| Kết quả trả về là file YAML khó đọc | Báo cáo HTML trực quan, phân loại rõ ràng |
| Không lưu lại lịch sử các lần quét | Có hệ thống lịch sử, tìm kiếm và lọc đầy đủ |

### Ai sử dụng ORT Web?

- **Lập trình viên** — kiểm tra thư viện mã nguồn mở trước khi đưa tính năng lên production
- **Bộ phận kiểm soát tuân thủ** — rà soát giấy phép phần mềm trên toàn bộ dự án
- **Kỹ sư vận hành** — tích hợp vào pipeline kiểm thử và chạy quét định kỳ

### ORT Web hỗ trợ ngôn ngữ lập trình nào?

| Ngôn ngữ | Trình quản lý gói được hỗ trợ |
|----------|-------------------------------|
| Python | pip, Poetry |
| Java / Kotlin | Maven, Gradle |
| JavaScript / TypeScript | npm, Yarn, pnpm |
| Go | Go modules |
| Rust | Cargo |
| C# / .NET | NuGet |
| C / C++ | Conan |
| Ruby | Bundler |
| PHP | Composer |
| Swift | Swift PM |

---

## 2. Yêu cầu hệ thống

Trước khi cài đặt, hãy kiểm tra máy tính đã có đủ các phần mềm sau chưa:

| Phần mềm | Phiên bản tối thiểu | Cách kiểm tra |
|----------|--------------------|--------------:|
| Python | 3.9 trở lên | `python --version` |
| Java | 21 trở lên | `java -version` |

**Riêng với Linux** — cần cài thêm để hiển thị hộp thoại chọn thư mục:
- Máy dùng GNOME: `sudo apt install zenity`
- Máy dùng KDE: `sudo apt install kdialog`

---

## 3. Cài đặt và khởi chạy lần đầu

### Bước 1: Sao chép thư mục ORT Web vào máy

Nhận thư mục `ort-web` từ quản trị viên (qua USB, ổ dùng chung, hoặc file nén) rồi sao chép vào máy. Ví dụ:

```
Windows:  C:\Tools\ort-web
macOS:    /Users/ten-ban/Tools/ort-web
Linux:    /home/ten-ban/Tools/ort-web
```

Mở Terminal (hoặc Command Prompt trên Windows) rồi di chuyển vào thư mục đó:

```bash
cd /đường-dẫn-đến/ort-web
```

### Bước 2: Tạo môi trường Python riêng

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
```

### Bước 3: Cài đặt ORT Web

```bash
pip install -e .
```

Sau bước này, lệnh `ort-web` sẽ được cài vào môi trường.

### Bước 4: Tạo lối tắt toàn cục (tùy chọn)

Nếu muốn gõ `ort-web` từ bất kỳ thư mục nào mà không cần phải vào thư mục cài đặt:

```bash
# macOS / Linux
sudo ln -sf $(which ort-web) /usr/local/bin/ort-web
```

### Bước 5: Khởi chạy

```bash
ort-web               # khởi động và tự mở trình duyệt
ort-web open          # tương tự
ort-web open -p 3000  # dùng cổng 3000 thay vì 8000 mặc định
```

Trình duyệt sẽ tự động mở tại `http://localhost:8000`.

---

## 4. Giao diện tổng quan

Màn hình chính khi mở ORT Web là **Dashboard** — nơi thực hiện toàn bộ thao tác chính.

```
┌─────────────────────────────────────────────────────────────┐
│  THANH BÊN TRÁI           │  KHU VỰC CHÍNH                  │
│  ─────────────────        │  ─────────────────              │
│  Dashboard            ←   │  [Thống kê tổng quan]           │
│  Lịch sử quét             │  Tổng số | Thành công | Lỗi     │
│                           │                                  │
│                           │  [Trạng thái ORT]               │
│                           │  ✅ Đã cài / ⚠️ Chưa cài        │
│                           │                                  │
│                           │  [Cài đặt ORT] (nếu chưa có)   │
│                           │                                  │
│                           │  [Quét dự án]                   │
│                           │  - Chọn thư mục                 │
│                           │  - Ngôn ngữ tự nhận diện        │
│                           │  - Nút [Bắt đầu quét]           │
└─────────────────────────────────────────────────────────────┘
```

### Ý nghĩa các ô thống kê

| Ô thống kê | Hiển thị gì |
|------------|-------------|
| **Tổng số lần quét** | Tổng tất cả các lần đã chạy |
| **Thành công** | Số lần hoàn tất không có lỗi |
| **Thất bại** | Số lần gặp lỗi trong quá trình chạy |
| **Trạng thái ORT** | ORT đã được cài và sẵn sàng chưa |

---

## 5. Cài đặt ORT

ORT Web tự động tải và cài đặt ORT — bạn chỉ cần làm một lần duy nhất, sau đó không cần lặp lại.

### Cách thực hiện

1. Trên Dashboard, tìm mục **"Cài đặt ORT"**
2. Nếu muốn chọn thư mục cài khác, nhấn **"Chọn thư mục"** trước
   - Mặc định: ứng dụng tự chọn thư mục phù hợp
3. Nhấn nút **"Cài đặt ORT"**
4. Theo dõi log cài đặt hiện ra bên dưới — quá trình này cần kết nối internet

### Các bước diễn ra tự động

```
[1] Tải phiên bản ORT mới nhất về máy
[2] Nhận diện hệ điều hành (macOS / Windows / Linux)
[3] Kiểm tra Java 21+ đã có chưa
[4] Giải nén file ORT vào thư mục đã chọn
[5] Tạo file khởi chạy (ort-web.sh hoặc ort-web.bat)
[6] Đánh dấu hoàn tất
```

### Sau khi xong

Ô trạng thái trên Dashboard chuyển sang **"Đã cài đặt ORT ✅"** — lúc này bạn có thể bắt đầu quét.

> **Lưu ý:** Nếu máy chưa có Java 21+, quá trình cài đặt sẽ dừng và báo lỗi. Hãy cài Java trước, rồi thực hiện lại bước này.

---

## 6. Quét một dự án

Đây là chức năng chính của ORT Web — phân tích toàn bộ thư viện mã nguồn mở trong một dự án phần mềm.

### Hướng dẫn từng bước

#### Bước 1: Chọn thư mục dự án

1. Nhấn nút **"Chọn thư mục"** trên Dashboard
2. Hộp thoại chọn thư mục của hệ điều hành hiện ra
3. Tìm đến thư mục gốc của dự án — nơi có các file như `pom.xml`, `package.json`, `requirements.txt`...
4. Nhấn **"Open"** hoặc **"Chọn"**

#### Bước 2: Kiểm tra ngôn ngữ được nhận diện

Sau khi chọn thư mục, ORT Web tự động quét file bên trong để xác định ngôn ngữ lập trình:

| Kết quả | Dựa vào đâu |
|---------|-------------|
| `Python` | Có file `.py`, `requirements.txt`, `pyproject.toml` |
| `Node.js` | Có file `package.json` |
| `Java` | Có file `pom.xml` hoặc `build.gradle` |
| v.v. | ... |

Bên cạnh đó, công cụ cũng hiển thị danh sách **trình quản lý gói phù hợp** được đề xuất cho ngôn ngữ đó.

> **Nhận diện sai?** Dùng menu thả xuống để tự chọn ngôn ngữ đúng trước khi chạy.

#### Bước 3: Bắt đầu quét

1. Xác nhận đường dẫn thư mục và ngôn ngữ đã đúng
2. Nhấn nút **"Quét"** (hoặc **"Phân tích"**)
3. Một **Bảng thông tin job** xuất hiện ngay trên Dashboard, hiển thị:
   - Tên và mã định danh của lần quét
   - Trạng thái hiện tại: Đang chờ → Đang chạy → Thành công / Thất bại
   - Log chạy trực tiếp theo thời gian thực

#### Bước 4: Theo dõi tiến trình

Quá trình quét luôn chạy tuần tự qua **3 giai đoạn** — bạn có thể xem từng bước trong log:

```
Giai đoạn 1: ANALYZE — Phân tích thư viện
  ort analyze -i /thư-mục/dự-án -o /thư-mục/output
  → Quét và liệt kê toàn bộ thư viện phụ thuộc
  → Sinh ra: analyzer-result.yml

Giai đoạn 2: ADVISE — Kiểm tra lỗ hổng bảo mật
  ort advise --advisors OSV -i analyzer-result.yml -o /thư-mục/output
  → Đối chiếu từng thư viện với cơ sở dữ liệu OSV
  → Sinh ra: advisor-result.yml

Giai đoạn 3: REPORT — Tạo báo cáo
  ort report --report-formats WebApp,StaticHtml -i advisor-result.yml -o /thư-mục/output
  → Xuất báo cáo dạng HTML dễ đọc
  → Sinh ra: scan-report-web-app.html, scan-report.html
```

#### Bước 5: Xem kết quả

Khi quét xong:
- Trạng thái chuyển sang **"Thành công"** (xanh lá) hoặc **"Thất bại"** (đỏ)
- Nếu phát hiện lỗ hổng, phần **Tóm tắt bảo mật** hiện ra bên dưới
- Danh sách file đã sinh ra kèm nút xem / tải về
- Nhấn **"Xem chi tiết"** để mở trang thông tin đầy đủ của lần quét

---

## 7. Đọc hiểu kết quả quét

### Tóm tắt lỗ hổng bảo mật

Sau khi quét xong, ORT Web tổng hợp kết quả từ OSV và hiển thị theo mức độ nguy hiểm:

```
┌────────────────────────────────────────┐
│  Tóm tắt lỗ hổng bảo mật              │
│  ─────────────────────────────────     │
│  🔴 Nghiêm trọng (Critical):  3       │
│  🟠 Cao (High):               12      │
│  🟡 Trung bình (Medium):      8       │
│  🟢 Thấp (Low):               5       │
└────────────────────────────────────────┘
```

**Ý nghĩa từng mức:**
- **Nghiêm trọng (Critical)** — Có thể bị tấn công từ xa mà không cần đăng nhập. Cần vá ngay.
- **Cao (High)** — Rủi ro lớn. Cần xử lý trước lần phát hành kế tiếp.
- **Trung bình (Medium)** — Ảnh hưởng vừa phải. Lên kế hoạch vá trong sprint sắp tới.
- **Thấp (Low)** — Tác động nhỏ. Có thể xử lý khi có thời gian.

### Các file kết quả được tạo ra

| File | Nội dung |
|------|----------|
| `analyzer-result.yml` | Toàn bộ cây thư viện phụ thuộc, thông tin giấy phép, metadata |
| `advisor-result.yml` | Danh sách lỗ hổng từ OSV, mã CVE, phiên bản bị ảnh hưởng |
| `scan-report-web-app.html` | Báo cáo web tương tác — phù hợp để duyệt và tra cứu |
| `scan-report.html` | Báo cáo HTML tĩnh — phù hợp để lưu trữ hoặc gửi cho người khác |

### Cách đọc báo cáo HTML

1. Nhấn vào file báo cáo HTML trên trang chi tiết lần quét
2. Báo cáo mở trong tab trình duyệt mới
3. Các mục cần chú ý:

| Mục trong báo cáo | Xem gì |
|-------------------|--------|
| **Tóm tắt (Summary)** | Con số tổng quan, phân loại theo mức độ |
| **Thư viện (Dependencies)** | Cây phụ thuộc đầy đủ kèm giấy phép từng gói |
| **Lỗ hổng (Vulnerabilities)** | Mã CVE, gói bị ảnh hưởng, điểm CVSS, phiên bản đã vá |
| **Giấy phép (Licenses)** | Tổng hợp giấy phép đang dùng, vi phạm chính sách nếu có |

---

## 8. Lịch sử quét và tìm kiếm

Trang **Lịch sử quét** lưu lại toàn bộ các lần đã chạy, giúp bạn tra cứu và so sánh kết quả theo thời gian.

### Cách vào

Nhấn **"Lịch sử quét"** ở thanh bên trái.

### Thông tin hiển thị trên mỗi thẻ

- **Tên** — tên thư mục dự án được lấy làm tên lần quét
- **Ngôn ngữ** — ngôn ngữ đã nhận diện
- **Trạng thái** — nhãn màu (Thành công / Thất bại / Đang chạy / Đang chờ / Đã hủy)
- **Thời điểm tạo** — khi nào lần quét được gửi đi
- **Thời gian chạy** — mất bao lâu để hoàn thành

### Bộ lọc tìm kiếm

| Bộ lọc | Cách dùng |
|--------|----------|
| **Tìm theo tên** | Gõ vào ô tìm kiếm — kết quả lọc ngay |
| **Trạng thái** | Chọn từ danh sách: Tất cả / Thành công / Thất bại / Đang chạy / Đang chờ / Đã hủy |
| **Ngôn ngữ** | Chọn từ danh sách: Tất cả / Python / Java / Node.js / Go / v.v. |
| **Khoảng thời gian** | Nhấn nút nhanh: 24 giờ / 7 ngày / 30 ngày / 90 ngày |
| **Ngày tùy chỉnh** | Nhấn "Tùy chỉnh" rồi chọn ngày bắt đầu và kết thúc |

### Phân trang

- Mỗi trang hiển thị 10 lần quét
- Dùng các nút số ở cuối trang để chuyển trang
- Bộ lọc áp dụng trên toàn bộ kết quả, không chỉ trang hiện tại

### Xem lại một lần quét cũ

Nhấn nút **"Xem kết quả"** trên thẻ tương ứng để vào trang chi tiết.

---

## 9. Xem và tải báo cáo

### Vào từ trang Lịch sử quét

1. Tìm lần quét cần xem
2. Nhấn **"Xem kết quả"**

### Nội dung trang chi tiết

Trang chi tiết một lần quét bao gồm:

1. **Thông tin chung** — tên, trạng thái, ngôn ngữ, thời gian bắt đầu/kết thúc, lệnh ORT đã dùng
2. **Nhật ký thực thi** — log đầy đủ của lần chạy, có thể thu gọn/mở rộng
3. **File đã sinh ra** — bảng liệt kê tất cả file output:
   - Tên file
   - Dung lượng
   - Loại file (YAML, HTML, v.v.)
   - Nút xem trực tiếp và nút tải về
4. **Tóm tắt lỗ hổng** — phân loại theo mức độ nguy hiểm

### Xem báo cáo HTML ngay trên trình duyệt

- Nhấn vào **biểu tượng mắt** hoặc tên file HTML
- Báo cáo mở trong tab mới
- Dùng các mục điều hướng trong báo cáo để tìm thông tin cần thiết

### Tải file về máy

- Nhấn **biểu tượng tải xuống** bên cạnh file muốn lấy
- File lưu vào thư mục tải về mặc định của trình duyệt
- Có thể tải: `analyzer-result.yml`, `advisor-result.yml`, các file báo cáo HTML

### Sao chép lệnh ORT đã dùng

- Trên trang chi tiết, tìm mục **"Lệnh thực thi"**
- Nhấn **"Sao chép"** để lấy toàn bộ lệnh ORT vào clipboard
- Tiện khi cần tái hiện lại lần quét theo cách thủ công

---

## 10. Đổi ngôn ngữ giao diện

ORT Web hỗ trợ **Tiếng Việt** (mặc định) và **Tiếng Anh**.

### Cách đổi

1. Tìm nút chọn ngôn ngữ ở góc trên bên phải màn hình
2. Nhấn **"Tiếng Việt"** hoặc **"English"**
3. Toàn bộ giao diện — nhãn, nút bấm, thông báo — chuyển ngay lập tức
4. Lựa chọn được lưu lại tự động, lần sau mở không cần chọn lại

---

## 11. Cập nhật ORT Web

### Kiểm tra phiên bản đang dùng

```bash
ort-web version
# hoặc
ort-web -V
```

### Nâng lên phiên bản mới hơn

Liên hệ quản trị viên để nhận thư mục `ort-web` phiên bản mới. Sau đó thực hiện:

1. **Dừng** ORT Web đang chạy — đóng cửa sổ Terminal
2. **Sao chép** thư mục mới vào máy (thay thế cái cũ hoặc đặt song song)
3. **Cài lại** trong thư mục mới:

```bash
cd /đường-dẫn-đến/ort-web-mới
source .venv/bin/activate    # macOS / Linux
.venv\Scripts\activate       # Windows
pip install -e .
```

4. **Khởi chạy** lại: `ort-web open`

> **Muốn giữ lịch sử quét cũ?** Sao chép thư mục `runtime/` từ phiên bản cũ sang thư mục phiên bản mới trước khi khởi chạy.

### Cập nhật ORT (không phải ORT Web)

Để lấy phiên bản ORT mới nhất, vào Dashboard và chạy lại quy trình **"Cài đặt ORT"** — ứng dụng luôn tải phiên bản mới nhất có sẵn.

---

## 12. Xử lý các lỗi thường gặp

### Lỗi "ORT chưa được cài đặt" hoặc không tìm thấy ORT

**Nguyên nhân:** Chưa chạy bước cài đặt ORT, hoặc cài nhưng không đúng thư mục.

**Cách khắc phục:**
1. Vào Dashboard
2. Nhấn "Cài đặt ORT" và làm theo hướng dẫn
3. Nếu đã cài thủ công từ trước, kiểm tra lại đường dẫn đến file ORT trong biến môi trường PATH

---

### Lỗi "Không tìm thấy Java" khi cài ORT

**Nguyên nhân:** ORT bắt buộc cần Java 21 trở lên, nhưng máy chưa cài hoặc Java không nằm trong PATH.

**Cách khắc phục:**
1. Cài Java 21+ — có thể dùng [Eclipse Temurin](https://adoptium.net/)
2. Kiểm tra: lệnh `java -version` phải trả về `21.x.x` trở lên
3. Thử lại bước cài ORT

---

### Lần quét thất bại ngay khi bắt đầu

**Nguyên nhân:** Thiếu trình quản lý gói, lỗi mạng, hoặc cấu hình ORT không đúng.

**Cách khắc phục:**
1. Vào trang chi tiết lần quét và đọc kỹ phần log
2. Thông báo lỗi thường xuất hiện ở cuối log
3. Một số trường hợp phổ biến:
   - `pip not found` → cài pip hoặc kích hoạt đúng môi trường Python
   - `mvn not found` → cài Maven
   - Timeout mạng → kiểm tra kết nối internet (bước Advise cần truy cập OSV)

---

### Hộp thoại chọn thư mục không mở được (Linux)

**Nguyên nhân:** Chưa cài `zenity` hoặc `kdialog`.

**Cách khắc phục:**
```bash
sudo apt install zenity      # máy dùng GNOME / Ubuntu
sudo apt install kdialog     # máy dùng KDE
```

---

### Cổng 8000 đã bị chiếm

**Cách khắc phục:**
```bash
ort-web open -p 3000    # đổi sang bất kỳ cổng nào còn trống
```

---

### Nhận diện sai ngôn ngữ của dự án

**Cách khắc phục:** Dùng menu thả xuống ngay trên Dashboard để tự chọn ngôn ngữ đúng, rồi mới nhấn "Quét".

---

## 13. Câu hỏi thường gặp

**Quét mất bao lâu?**
Tùy vào số lượng thư viện phụ thuộc trong dự án:
- Dự án nhỏ (dưới 50 thư viện): khoảng 2–5 phút
- Dự án trung bình (50–200 thư viện): khoảng 5–15 phút
- Dự án lớn (trên 200 thư viện): có thể 15–60 phút

**Có thể chạy nhiều lần quét cùng lúc không?**
Có, tối đa **2 lần quét song song**. Các lần thêm sẽ xếp hàng chờ và tự động chạy khi có chỗ trống.

**File báo cáo lưu ở đâu?**
Trong thư mục `runtime/artifacts/` bên trong thư mục ORT Web. Ngoài ra có thể tải trực tiếp từ giao diện web.

**Trạng thái "Thất bại" có nghĩa là gì?**
ORT đã dừng lại vì gặp lỗi. Vào trang chi tiết và đọc log để tìm nguyên nhân cụ thể. Thường gặp nhất là: thiếu trình quản lý gói, không phân giải được thư viện, hoặc mạng bị gián đoạn.

**Có chạy lại được lần quét đã thất bại không?**
Hiện tại chưa có nút "Chạy lại". Bạn cần quay về Dashboard và tạo lần quét mới với cùng thư mục dự án.

**Làm sao biết giấy phép nào đang vi phạm?**
Mục **"Giấy phép"** trong báo cáo HTML liệt kê tất cả. Giấy phép nào bị đánh dấu vi phạm phụ thuộc vào chính sách cấu hình trong file `~/.ort/config.yml`. Hỏi thêm bộ phận kiểm soát tuân thủ của tổ chức để biết chính sách áp dụng.

---

## Phụ lục: Tóm tắt lệnh CLI

| Lệnh | Tác dụng |
|------|----------|
| `ort-web` | Khởi động server và mở trình duyệt |
| `ort-web open` | Giống lệnh trên |
| `ort-web open -p 3000` | Khởi động trên cổng 3000 |
| `ort-web open --reload` | Chế độ phát triển, tự tải lại khi có thay đổi |
| `ort-web version` | Xem phiên bản hiện tại |
| `ort-web -V` | Tương tự `version` |

## Phụ lục: Sơ đồ quy trình quét

```
Người dùng
    │
    ▼
[1] Chọn thư mục dự án
    │
    ▼
[2] ORT Web tự nhận diện ngôn ngữ lập trình
    │
    ▼
[3] Tự tạo file cấu hình:
    - ~/.ort/ort.properties (bật các trình quản lý gói phù hợp)
    - project/.ort.yml (loại trừ các thư mục không cần quét)
    │
    ▼
[4] Lần quét được tạo và xếp vào hàng chờ
    │
    ▼
[5] ORT chạy tuần tự 3 giai đoạn:
    Analyze → Advise (OSV) → Report (HTML)
    │
    ▼
[6] Kết quả đầu ra:
    - analyzer-result.yml
    - advisor-result.yml
    - scan-report-web-app.html
    - scan-report.html
    │
    ▼
[7] Xem tóm tắt lỗ hổng và tải báo cáo
```

---

*Cập nhật lần cuối: Tháng 4 năm 2026 | ORT Web v0.3.0*
