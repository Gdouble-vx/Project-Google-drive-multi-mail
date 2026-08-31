# 📁 Google Drive Multi Mail

ระบบจัดการไฟล์บน Google Drive หลายบัญชี พร้อม AI จัดการอัตโนมัติ

## 🎯 Features

- 🔗 **เชื่อมต่อหลาย Drive** - เพิ่ม Gmail หลายบัญชีเพื่อรวมพื้นที่จัดเก็บ
- ✂️ **แบ่งไฟล์อัตโนมัติ** - ไฟล์ >10GB ถูกแบ่งและจัดเก็บแยก Drive
- 🤖 **AI จัดการไฟล์** - ค้นหา จัดเรียง และจัดการไฟล์ด้วย AI
- 🔍 **ค้นหาได้ทุกที่** - ค้นหาไฟล์จากทุก Drive ที่เชื่อมต่อไว้
- 🌐 **Web GUI** - หน้าต่างจัดการไฟล์ผ่านเบราว์เซอร์
- 🔒 **เข้ารหัสข้อมูล** - รหัสผ่านและ Token ถูกเข้ารหัสด้วย Fernet

## 📋 Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   GUI/Web   │────▶│  FastAPI     │────▶│  AI Agent   │
│  (Browser)  │◀────│  Backend     │◀────│  (Manager)  │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                     │
                    ┌──────▼───────┐     ┌──────▼──────┐
                    │   SQLite     │     │ Google Drive│
                    │  Database    │     │   API       │
                    └──────────────┘     └──────┬──────┘
                                                │
                              ┌──────────────────┼──────────────────┐
                              │                  │                  │
                       ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
                       │  Drive #1   │   │  Drive #2   │   │  Drive #3   │
                       │  (Gmail 1)  │   │  (Gmail 2)  │   │  (Gmail 3)  │
                       └─────────────┘   └─────────────┘   └─────────────┘
```

## 🚀 Setup

### 1. ติดตั้ง Dependencies

```bash
pip install -r requirements.txt
```

### 2. ตั้งค่า Google OAuth2

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/)
2. สร้าง Project ใหม่หรือเลือก Project ที่มี
3. เปิดใช้งาน **Google Drive API**
4. สร้าง **OAuth 2.0 Client ID** (Web Application)
5. เพิ่ม Redirect URI: `http://localhost:8080/api/auth/callback`
6. คัดลอก Client ID และ Client Secret ไปใส่ใน `.env`

### 3. ตั้งค่า Environment

```bash
cp .env.example .env
# แก้ไข .env ใส่ค่า GOOGLE_CLIENT_ID และ GOOGLE_CLIENT_SECRET
```

### 4. รัน Application

```bash
python main.py
```

เปิดเบราว์เซอร์ไปที่ `http://localhost:8080`

## 📂 โครงสร้างโปรเจกต์

```
├── main.py                    # Entry point
├── requirements.txt           # Dependencies
├── app/
│   ├── database/
│   │   ├── models.py         # SQLAlchemy models
│   │   └── manager.py        # Database CRUD operations
│   ├── drive/
│   │   ├── gdrive.py         # Google Drive API integration
│   │   └── splitter.py       # File splitting/merging engine
│   ├── ai/
│   │   └── agent.py          # AI storage management agent
│   ├── api/
│   │   └── routes.py         # FastAPI endpoints
│   └── utils/
│       └── crypto.py         # Encryption utilities
├── static/
│   ├── css/style.css         # Dashboard styles
│   └── js/app.js             # Dashboard JavaScript
└── templates/
    ├── index.html             # Landing page
    └── dashboard.html         # Main dashboard
```

## 📡 API Endpoints

### Accounts
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/accounts` | เพิ่มบัญชีใหม่ |
| GET    | `/api/accounts` | รายชื่อบัญชีทั้งหมด |
| DELETE | `/api/accounts/{id}` | ลบบัญชี |

### Files
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/files/upload` | อัพโหลดไฟล์ (auto-split) |
| GET    | `/api/files` | รายชื่อไฟล์ |
| GET    | `/api/files/{id}` | รายละเอียดไฟล์ |
| GET    | `/api/files/{id}/download` | ดาวน์โหลดไฟล์ |
| GET    | `/api/files/{id}/location` | ตำแหน่งไฟล์ (chunk map) |
| DELETE | `/api/files/{id}` | ลบไฟล์ |

### Search
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/search?q=...` | ค้นหาไฟล์ |

### Drives
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/drives` | รายชื่อ Drive ทั้งหมด |
| GET    | `/api/drives/summary` | สรุปพื้นที่รวม |
| POST   | `/api/drives/sync` | ซิงค์ข้อมูลจาก Drive |

## 🤖 AI Agent Features

AI Agent ทำหน้าที่เป็นตัวกลางระหว่าง GUI, Database และ Google Drive:

1. **ตัดสินใจแบ่งไฟล์** - วิเคราะห์ขนาดไฟล์และพื้นที่ว่างของแต่ละ Drive
2. **เลือก Drive ที่เหมาะสม** - จัดวาง chunks บน Drive ที่มีพื้นที่มากที่สุด
3. **ค้นหาไฟล์** - ค้นจากชื่อ แท็ก หรือคำอธิบายผ่าน Search Index
4. **ติดตามตำแหน่ง** - บันทึกว่าแต่ละ chunk อยู่บน Drive ไหน
5. **รวมไฟล์** - รวม chunks กลับเป็นไฟล์เดิมเมื่อดาวน์โหลด

## ⚠️ หมายเหตุ

- ไฟล์จะถูกแบ่งเมื่อมีขนาดเกิน **10GB**
- ต้องมี Google OAuth2 Client ID สำหรับเชื่อมต่อ Drive
- ข้อมูลรหัสผ่านถูกเข้ารหัสด้วย Fernet encryption
- ฐานข้อมูล SQLite เก็บในโฟลเดอร์ `data/`
