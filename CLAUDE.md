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
