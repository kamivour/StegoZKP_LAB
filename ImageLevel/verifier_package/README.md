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

### Verify ảnh stego (REQUIRED: --key)

```bash
python scripts/verify.py path/to/stego_image.png --key "your_secret_key"
```

### Verify với verbose output

```bash
python scripts/verify.py path/to/stego_image.png --key "your_secret_key" -v
```

### Verify và output JSON

```bash
python scripts/verify.py path/to/stego_image.png --key "your_secret_key" --json
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

## 🔑 Bảo mật (v2.0)

- **Secret key**: PHẢI được truyền qua kênh an toàn (HTTPS, encrypted message, ...)
- **Không lưu trong ảnh**: Ảnh chỉ chứa hash của key để verify
- **Verification key**: Là public key của ZK circuit, không cần bảo mật
- **Backward compatible**: Vẫn hỗ trợ ảnh cũ (v1.0) nhưng sẽ hiển thị warning
