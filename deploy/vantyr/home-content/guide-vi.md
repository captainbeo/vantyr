# Vantyr API

Truy cập Claude & Codex cao cấp với chi phí chỉ bằng một phần nhỏ so với giá chính thức — một khóa duy nhất, một bảng điều khiển duy nhất, thanh toán theo mức dùng hoặc không giới hạn.

## Bắt đầu trong 5 phút

1. **Tạo tài khoản** — [Đăng ký](/register), sau đó [đăng nhập](/login). Tiếp theo, hãy liên kết **Telegram** của bạn trong mục Bảo mật → Liên kết tài khoản để nhận **$5 tín dụng miễn phí** — đủ để trải nghiệm trọn vẹn mọi mô hình, không cần thẻ.
2. **Nạp tiền** — mở trang [Ví](/wallet), chọn số tiền cần nạp và thanh toán bằng thẻ (Stripe).
   Mức giá PAYG áp dụng cho từng yêu cầu; xem trang [Mô hình & Giá cả](/pricing).
3. **Tạo khóa API** — truy cập [Khóa API](/keys), nhấp **Tạo**, đặt tên cho khóa rồi sao chép khóa của bạn.
   > **Mẹo:** hãy giữ nguyên tùy chọn **Hạn mức không giới hạn** đang được tích. Trường hạn mức giới hạn tổng chi tiêu của khóa này; nếu để không giới hạn, số dư ví của bạn sẽ là thứ quyết định mức chi.
4. **Trỏ công cụ của bạn tới Vantyr** — URL cơ sở `https://vantyr.example.com/v1` (địa chỉ tạm; xem tên miền khi ra mắt), header xác thực `Authorization: Bearer sk-...`.

## Sử dụng Codex CLI

Thêm nội dung sau vào `~/.codex/config.toml` (tạo tệp nếu tệp chưa tồn tại):

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Sau đó export khóa của bạn và chạy:

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Mô hình đề xuất:** `gpt-6-astra` (hàng đầu), `gpt-5-6-luna` (tiết kiệm). Các mô hình Claude hoạt động trong bất kỳ công cụ nào tương thích với OpenAI.

## Dùng với bất kỳ client tương thích OpenAI

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Dành cho người dùng Claude Code và Anthropic SDK: đặt `ANTHROPIC_BASE_URL` thành `https://vantyr.example.com` và `ANTHROPIC_API_KEY` thành khóa Vantyr của bạn.

## Gói hàng tháng không giới hạn — $180

Chỉ một lần thanh toán, 30 ngày, dùng Claude + Codex **không giới hạn**. Không tính phí theo từng token, không có hóa đơn bất ngờ.

- Giá cố định $180/tháng, hủy bất cứ lúc nào (quyền truy cập sẽ hết hạn; mua lại để gia hạn)
- Bao gồm mọi mô hình, giữ nguyên giao diện API
- Áp dụng giới hạn tốc độ theo chính sách sử dụng hợp lý

[Đăng ký gói trên trang Giá cả](/pricing)

## Câu hỏi

- **Gặp lỗi "insufficient quota" (hạn mức không đủ)?** Ví của bạn đã hết tiền — hãy nạp tiền trên trang [Ví](/wallet).
- **Gặp lỗi "429 rate limit" (giới hạn tốc độ)?** Bạn đã chạm giới hạn số yêu cầu mỗi phút. Hãy đợi một phút, hoặc liên hệ chúng tôi để nâng giới hạn.
- Lịch sử sử dụng: trang [Nhật ký](/logs) hiển thị từng yêu cầu, số token và chi phí của nó.
