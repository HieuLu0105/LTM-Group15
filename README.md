# Network Monitoring Dashboard

Hệ thống giám sát tình trạng máy tính/server theo thời gian thực (CPU, RAM, network...), xây dựng trên nền tảng giao thức **WebSocket**.

---

## Định hướng làm đề tài của nhóm

Nhóm xây dựng một **dashboard giám sát mạng/hệ thống theo thời gian thực**, gồm 3 thành phần chính:

- **Agent (Python + psutil)**: chạy trên từng máy cần giám sát, thu thập chỉ số CPU, RAM, network, disk theo chu kỳ và gửi dữ liệu lên server.
- **Server (Python + websockets)**: nhận dữ liệu từ các agent, lưu trạng thái mới nhất của từng máy, và **đẩy (push) dữ liệu real-time** tới mọi dashboard đang kết nối — không cần polling.
- **Dashboard (HTML/JS + Chart.js)**: giao diện web hiển thị số liệu và biểu đồ trực quan cho từng máy, cập nhật tức thời khi có dữ liệu mới.

Lý do chọn WebSocket làm giao thức lõi: đây là giao thức **full-duplex, giữ kết nối liên tục**, phù hợp cho bài toán cần đẩy dữ liệu liên tục từ server xuống client mà không tốn chi phí request/response lặp lại như HTTP polling — đúng bản chất của một hệ thống giám sát real-time.

Ngoài mục tiêu học thuật (minh họa cách giao thức WebSocket hoạt động, từ handshake HTTP nâng cấp lên kết nối TCP bền), nhóm hướng đề tài này có khả năng phát triển thành sản phẩm thực tế cho các doanh nghiệp vừa và nhỏ cần theo dõi hạ tầng IT nội bộ mà không muốn phụ thuộc vào các nền tảng giám sát cloud phức tạp/tốn phí.

---

## Project tham khảo

| Project | Mô tả | Link |
|---|---|---|
| **websockets** (python-websockets) | Thư viện WebSocket chuẩn, phổ biến nhất cho Python, dùng làm nền cho server. | https://github.com/python-websockets/websockets |
| **psutil** | Thư viện lấy thông tin hệ thống (CPU, RAM, network, disk, process) đa nền tảng — dùng cho phần agent. | https://github.com/giampaolo/psutil |
| **Glances** | Công cụ giám sát hệ thống bằng Python, có giao diện web, hỗ trợ nhiều máy (client/server). | https://github.com/nicolargo/glances |
| **Netdata** | Nền tảng giám sát hạ tầng thời gian thực rất phổ biến, hiển thị hàng nghìn chỉ số hệ thống theo thời gian thực. | https://github.com/netdata/netdata |
| **ws (Node.js)** | Thư viện WebSocket tối giản cho Node.js — tham khảo cách thiết kế server/broadcast dù nhóm dùng Python. | https://github.com/websockets/ws |
| **aws-samples/websocket-chat-application** | Ví dụ ứng dụng chat dùng WebSocket — tham khảo mô hình broadcast tin nhắn tới nhiều client. | https://github.com/aws-samples/websocket-chat-application |

---

## Nhóm sẽ phát triển thêm những gì

- **Glances** và **Netdata** đã rất mạnh nhưng khá "nặng" và phức tạp để cài đặt/tùy biến cho người mới; nhóm hướng tới một bản **tối giản, dễ triển khai trong vài phút**, phù hợp cho doanh nghiệp nhỏ không có đội IT chuyên trách.
- Các project tham khảo (Glances, Netdata) tập trung thuần vào **giám sát**; nhóm dự định **kết hợp thêm kênh chat/thông báo nội bộ** trên cùng một kết nối WebSocket (cùng hạ tầng, khác loại message) — biến dashboard thành một "phòng vận hành" (ops room) vừa xem số liệu vừa trao đổi khi có sự cố, thay vì phải mở thêm công cụ chat riêng.
- Thêm **cơ chế cảnh báo (alerting) trực quan ngay trên dashboard** (đổi màu/thông báo khi vượt ngưỡng CPU/RAM) — mức cơ bản dễ hiểu cho người không chuyên kỹ thuật, khác với các tool tham khảo thường yêu cầu cấu hình alerting phức tạp qua file config.
- Thiết kế dữ liệu và giao diện **hướng tới người dùng không rành kỹ thuật** (ngôn ngữ đơn giản, không thuật ngữ chuyên sâu), dựa trên khảo sát ý kiến thực tế nhóm đã thực hiện với cả nhóm đối tượng kỹ thuật và phi kỹ thuật.
- Về lâu dài, nhóm cân nhắc thêm **lịch sử dữ liệu (không chỉ real-time)** và khả năng xem trên điện thoại — hai tính năng được nhiều người được khảo sát đánh giá là "có thì tốt".

---

## Cấu trúc thư mục

```
/agent      # Script Python thu thập chỉ số hệ thống, gửi qua WebSocket
/server     # WebSocket server (Python), quản lý kết nối và broadcast dữ liệu
/dashboard  # Giao diện web (HTML/CSS/JS + Chart.js)
README.md
```

## Thành viên nhóm & phân công

| Thành viên | Vai trò |
|---|---|
| _Lư Hoàng Minh Hiếu_ | Backend / WebSocket Server |
| _Đặng Phúc Hải Tịnh_ | Agent / Data Collector |
| _Nguyễn Hồng Đức_ | Dashboard / Frontend |# LTM-Group15
Group project for Network Developing by Group 15
