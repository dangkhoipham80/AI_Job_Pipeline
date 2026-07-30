---
name: tailor-cv
description: >
  Tailor Master CV (Awesome-CV LaTeX) tới một Job Description cụ thể — trích
  requirement, gap-analysis, rewrite có kiểm soát các section, sinh cover letter,
  build PDF. Dùng khi cần điều chỉnh CV cho một job đã chọn. Nguyên tắc số 1:
  KHÔNG BỊA — chỉ nhấn mạnh/diễn đạt lại dữ kiện có thật trong Master CV.
---

# SKILL: tailor-cv

Đây là spec cho engine tailor CV của JobPilot (xem `PLAN.md`). Nó vừa là tài liệu
thiết kế, vừa là "system prompt sống" cho Claude khi tailor.

## 0. Nguyên tắc tối thượng — Truthfulness

> **KHÔNG BAO GIỜ thêm kỹ năng, công nghệ, kinh nghiệm, con số, hay thành tựu
> không tồn tại trong Master CV.**

Được phép:
- ✅ **Nhấn mạnh** kinh nghiệm/skill có thật khớp JD (đưa lên trước, in đậm/`\tech{}`).
- ✅ **Diễn đạt lại** bằng từ khoá của JD *nếu* nội dung tương đương đã có (vd JD viết "RESTful microservices" mà CV có "RESTful APIs + microservices" → ok gộp).
- ✅ **Ẩn/rút gọn** phần ít liên quan để CV gọn 1 trang.
- ✅ **Sắp xếp lại** thứ tự project/experience theo độ liên quan.

Bị cấm:
- ❌ Thêm skill chưa từng xuất hiện (vd JD cần Kafka mà CV không có → **không** thêm).
- ❌ Bịa metric ("tăng 40% hiệu năng") nếu Master CV không ghi.
- ❌ Đổi năm/công ty/chức danh.
- ❌ Suy diễn skill ("dùng Spring Boot nên chắc biết Hibernate").

Nếu JD yêu cầu skill user **không có**: KHÔNG thêm vào CV. Thay vào đó đánh dấu trong
**gap report** để user tự quyết (học thêm / bỏ qua job / ghi chú trong cover letter là "sẵn sàng học").

## 1. Input / Output

**Input:**
- `job`: object theo `Job` schema (§3.1 PLAN.md) — quan trọng nhất là `description_md`, `skills`, `title`, `level`, `company`.
- `master_cv`: nội dung `resume/*.tex` (nguồn sự thật duy nhất).

**Output** (ghi vào `out/<job_id>/` + DB):
- **CV structured JSON** (format chung với CV Studio — PLAN.md §5.6.1): đây là output chính của agent. Serialize ra `resume/*.tex` qua Jinja2 (bản sao, KHÔNG ghi đè Master). Nhờ chung format, bản agent-tailor và bản user-edit trong Studio đi chung pipeline diff/version/preview; lưu vào `cv_versions` với `author='agent'`.
- `cv.pdf` đã build.
- `cover_letter.tex` + `.pdf`.
- `meta.json`: `{ match_score, changes[], gaps[], keywords_added[] }` — dùng để render **diff** trên Web/Slack.

## 2. Quy trình 5 bước

### Bước 1 — Trích requirement từ JD
Phân tách `description_md` thành:
- `must_have`: skill/kinh nghiệm bắt buộc.
- `nice_to_have`: ưu tiên.
- `soft/culture`: teamwork, agile, ngôn ngữ...
- `keywords`: danh sách từ khoá ATS (Java, Spring Boot, PostgreSQL, CI/CD...).

### Bước 2 — Gap analysis vs Master CV
Với mỗi requirement, phân loại:
- `HAVE` — có trong Master CV (ghi rõ nằm ở section nào).
- `PARTIAL` — có liên quan gần (diễn đạt lại được).
- `MISSING` — không có (→ vào gap report, **không** đưa vào CV).

Tính `match_score` = trọng số(HAVE + 0.5·PARTIAL) / tổng requirement (must_have nặng hơn nice_to_have).

### Bước 3 — Rewrite có kiểm soát (per section)

Chỉ sửa các file `resume/*.tex`, giữ nguyên cú pháp Awesome-CV. Macro có sẵn:
`\tech{}` (đỏ đậm — highlight tech chính), `\techfe{}` (skyblue — frontend), `\cvsimpleentry`, `\cvitems`.

| Section | Được làm gì |
|---|---|
| `summary.tex` | Viết lại 2–3 câu hướng vào role của JD, dùng keyword có thật. Giữ ngắn gọn, giọng backend. |
| `skill.tex` | Bật/sắp xếp lại các dòng có thật để keyword must-have lên đầu. Bật lại dòng đang comment **nếu** skill đó user thật sự có. Không thêm skill mới. |
| `experience.tex` | Giữ nguyên facts. Có thể `\tech{}` hoá đúng tech JD cần; đưa bullet liên quan lên trước. |
| `project.tex` | Sắp xếp project liên quan nhất lên đầu; highlight tech khớp JD. Không đổi vai trò/nội dung. |
| `education.tex` / `honors.tex` | Hầu như giữ nguyên; chỉ đổi thứ tự nếu cần. |

**Rule độ dài**: giữ CV **1 trang**. Nếu tràn → rút phần ít liên quan (không xoá facts quan trọng).

### Bước 4 — Cover letter
Sinh `cover_letter.tex` (dùng class Awesome-CV `\cvletter` hoặc template riêng):
- Mở đầu: vị trí ứng tuyển + công ty (`job.title`, `job.company`).
- Thân: 2–3 điểm mạnh **có thật** khớp must-have, dẫn chứng từ experience/project.
- Nếu có `MISSING` quan trọng: 1 câu thể hiện tinh thần học hỏi (trung thực, không khẳng định đã biết).
- Kết: call-to-action lịch sự + thông tin liên hệ.
- Giọng: chuyên nghiệp, ngắn (<= 300 từ), không sáo rỗng.

### Bước 5 — Build & verify
- Copy `resume/` + assets vào `out/<job_id>/`, apply edits.
- Build bằng Docker LaTeX (lệnh trong `README.md`).
- **Verify**: build thành công + CV đúng 1 trang + không lỗi LaTeX undefined. Fail → trả lỗi cho orchestrator (state `FAILED`), không post CV hỏng.

## 3. Định dạng diff cho Slack (để user duyệt)

`meta.json.changes[]` mỗi phần tử:
```jsonc
{ "section": "summary", "before": "…", "after": "…", "reason": "khớp must-have 'distributed systems'" }
```
Slack hiển thị gọn: *"📝 Summary: nhấn 'distributed systems' (khớp JD) · Skills: đưa Docker/K8s lên đầu · Project: Slide AI lên #1 (khớp RAG/microservices)"* + `gaps` (⚠️ JD cần Kafka — bạn chưa có).

## 4. Vòng "Sửa" (edit loop)

Khi user bấm **✏️ Sửa** và nhập instruction (vd "rút gọn summary", "bỏ project Food Forum", "nhấn thêm Docker"):
- Áp dụng instruction **trong khuôn khổ truthfulness** (nếu instruction yêu cầu bịa → từ chối lịch sự, giải thích).
- Re-build, re-diff, post lại. Tối đa `K` vòng (config), sau đó nhắc user Approve/Bỏ.

## 5. Checklist trước khi trả kết quả
- [ ] Không có skill/metric/fact nào không thuộc Master CV.
- [ ] `match_score` và `gaps` đã tính.
- [ ] PDF build ok, đúng 1 trang.
- [ ] Cover letter đúng công ty/vị trí.
- [ ] `meta.json` đủ để render diff.
- [ ] Master CV (`resume/`) **không** bị ghi đè.
