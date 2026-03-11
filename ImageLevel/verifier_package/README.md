# ZK-SNARK Steganography Verifier Package (v2.0 - Secure)

## 🔐 Security Update (v2.0)

**QUAN TRỌNG:** Từ version 2.0, `secret_key` (chaos_key) **KHÔNG còn được lưu trong ảnh**.  
Bạn phải nhận secret_key qua một **kênh an toàn riêng** (secure channel).

## Setup

### 1. Cài đặt Node.js và snarkjs

```bash
# Cài đặt Node.js (nếu chưa có)
# Download từ: https://nodejs.org/

# Cài đặt snarkjs
npm install -g snarkjs
```

### 2. Cài đặt Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Kiểm tra setup

```bash
python scripts/verify.py --help
```

## Sử dụng

`chaos_key.txt` đã được ship sẵn trong package này — không cần flag `--key`.

### Verify ảnh stego (key tự động từ chaos_key.txt)

```bash
# Chạy từ thư mục verifier_package/ — chaos_key.txt được load tự động
python scripts/verify.py path/to/stego_image.png
```

### Verify với verbose output

```bash
python scripts/verify.py path/to/stego_image.png -v
```

### Verify và output JSON

```bash
python scripts/verify.py path/to/stego_image.png --json
```

### Override key thủ công (nếu cần)

```bash
python scripts/verify.py path/to/stego_image.png --key "your_secret_key"
```

## Cấu trúc Package

```
verifier_package/
├── src/zk_stego/          # Source code để extract/verify
├── circuits/compiled/build/
│   └── verification_key.json  # Public key (không cần bảo mật)
├── scripts/
│   └── verify.py          # Script verify
├── requirements.txt        # Python dependencies
└── README.md              # File này
```

## 🔑 Bảo mật

- **chaos_key.txt**: Key được ship một lần cùng với package này qua kênh an toàn;
  sau đó chỉ cần nhận stego image — key không đi kèm với từng ảnh
- **Không lưu trong ảnh**: Ảnh chỉ chứa SHA-256 hash của key để verify
- **Verification key**: Là public key của ZK circuit (`circuits/compiled/build/verification_key.json`), không cần bảo mật
- **Nếu chaos_key.txt bị thiếu**: Script sẽ báo lỗi rõ ràng và hướng dẫn cách cung cấp key
