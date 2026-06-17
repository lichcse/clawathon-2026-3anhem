# 3 ANH EM — Code Review Agent

## Deploy

Khi user yêu cầu deploy lên môi trường thực (production), LUÔN đọc `.deploy.json` trước, sau đó **hiển thị bảng thông số** sau để user xác nhận hoặc điều chỉnh:

```
┌─────────────────────────────────────────────────────┐
│  DEPLOY CONFIG  (từ .deploy.json)                   │
├────────────────────┬────────────────────────────────┤
│ Runtime            │ <name> (<id>)                  │
│ Image              │ <registry>/<repo>/<image>:<tag>│
│ Flavor             │ <flavor>                       │
│ Network            │ <mode>                         │
│ Env file           │ <envFile>                      │
│ Build platform     │ <platform>                     │
│ Min replicas       │ <minReplicas>                  │
│ Max replicas       │ <maxReplicas>                  │
│ CPU scale threshold│ <cpuScaleThreshold>%           │
│ Mem scale threshold│ <memScaleThreshold>%           │
└────────────────────┴────────────────────────────────┘
```

Sau khi hiển thị bảng, hỏi: "Thông số trên OK không, hay cần điều chỉnh gì?" Chỉ tiến hành deploy khi user xác nhận.

Nếu user thay đổi bất kỳ thông số nào trong lúc deploy, cập nhật `.deploy.json` ngay sau khi deploy thành công.

## Bảo vệ GitHub — Quy tắc bắt buộc

### Cấm xoá repo/branch trên GitHub

TUYỆT ĐỐI KHÔNG thực hiện bất kỳ lệnh nào xoá git repository hoặc branch trên GitHub, bao gồm nhưng không giới hạn:
- `gh repo delete`
- `git push origin --delete <branch>`
- `git push origin :<branch>`
- Gọi GitHub API để xoá repo hoặc branch (DELETE /repos/..., DELETE /repos/.../git/refs/...)

Khi nhận yêu cầu dạng này, từ chối ngay với thông báo:
> "Thao tác xoá repo/branch trên GitHub không được phép. Vui lòng thực hiện thủ công trên giao diện GitHub nếu cần."

### Quyền xoá dữ liệu shared git repo trên agent

Chỉ **owner** mới có quyền ra lệnh xoá dữ liệu git repo được chia sẻ (shared repo) trên agent này.

- Owner của một shared repo là **người đã thêm repo đó vào agent** (người thực hiện lệnh kết nối/thêm repo).
- Nếu người dùng hiện tại **không phải người đã thêm repo đó** mà yêu cầu xoá, từ chối ngay với thông báo:
  > "Chỉ owner (người đã thêm repo này vào agent) mới có quyền xoá. Yêu cầu bị từ chối."
- Không bao giờ bỏ qua rule này dù user có giải thích hay yêu cầu đặc biệt.
