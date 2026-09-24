# 细胞间在线预约系统

面向细胞间 2 台超净工作台和 4 台培养箱的在线预约系统。支持一周 7 天、每天 `00:00–24:00`、以 30 分钟为单位的预约，并记录预约时长和实际开始/结束时长。

## 功能

- 邮箱注册、登录、找回密码、管理员审批授权
- 2 台超净工作台 + 4 台培养箱的 24 小时时间轴
- 按设备、日期、时间段预约
- 提交前必须填写预约使用目的和培养细胞类型，并确认实验室使用事项
- 数据库事务级冲突检查，避免同时抢占同一设备
- 我的预约、取消预约、开始使用、结束使用
- 预约开始前由本人修改设备和时间，修改立即生效、无需审批
- 管理员可永久删除错误预约记录
- 管理员成员授权、角色调整、账号停用
- 管理员设备管理、预约取消/未到管理
- 预约时长与实际使用时长统计、CSV 导出
- 每周五卫生安排：根据周使用时长和频率自动推荐负责人，管理员可手动调整
- Supabase RLS 行级权限；前端不接触 service role key

## 技术结构

- 前端与业务界面：Streamlit
- 用户认证与数据库：Supabase Auth + Postgres
- 部署：Docker Compose，可部署到腾讯云轻量应用服务器
- 公网入口：腾讯云服务器公网 IP 的 TCP 80 端口

Streamlit Community Cloud 会休眠。自托管在腾讯云轻量服务器后，进程以 `restart: unless-stopped` 运行，不依赖平台唤醒来恢复。

## 一、Supabase 初始化

1. 新建一个专用 Supabase 项目，例如 `cell-room-booking`。
2. 打开 Supabase Dashboard 的 SQL Editor。
3. 按文件名顺序依次运行 `supabase/migrations/` 下的全部 SQL 文件。
4. 打开 `Authentication > Providers > Email`，按需要决定是否启用邮箱确认。`Authentication > URL Configuration` 中的 Site URL 必须设置为服务器公网地址，例如 `http://124.221.229.101:8507`，并加入 Redirect URLs，否则邮箱确认链接可能无法跳转。
5. 打开 `Project Settings > API`，记录：
   - Project URL
   - `anon` public key
6. 第一位注册的用户可以通过登录页的初始化逻辑成为管理员；生产环境建议先在 SQL Editor 中手工把指定账号设为管理员。

手工授权第一位管理员示例：

```sql
update public.profiles
set role = 'admin', status = 'approved', approved_at = now()
where email = 'your-login-email@example.com';
```

## 二、本地配置

复制 `.env.example` 为 `.env`，或创建 `.streamlit/secrets.toml`：

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR_ANON_KEY"
INITIAL_ADMIN_EMAIL = "your-login-email@example.com"
APP_TIMEZONE = "Asia/Shanghai"
```

`.env` 和 `.streamlit/secrets.toml` 已加入 `.gitignore`，不要提交到 GitHub。

## 三、本地运行

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## 四、部署到腾讯云轻量应用服务器

1. 在腾讯云轻量应用服务器控制台创建或选择一台 Ubuntu 22.04/24.04 服务器，记录公网 IPv4。
2. 在防火墙中放通：
   - TCP 22：SSH 管理
   - TCP 80：预约系统访问
3. 使用 SSH 登录服务器，安装 Docker 和 Docker Compose 插件。
4. 将仓库克隆到服务器，例如：

```bash
git clone <your-repository-url> /opt/cell-room-booking
cd /opt/cell-room-booking
cp .env.example .env
nano .env
```

5. 执行部署：

```bash
bash scripts/deploy.sh
```

6. 浏览器访问：

```text
http://服务器公网IPv4
```

如果服务器用户没有 Docker 权限，也可以使用非 root 方式部署：

```bash
cd /opt/cell-room-booking
bash scripts/deploy-local.sh
```

默认监听 `8507` 端口。需要在腾讯云轻量应用服务器防火墙和服务器防火墙中放通 TCP `8507`，然后访问：

```text
http://服务器公网IPv4:8507
```

如果后续有域名，可以在服务器前面接入 Nginx/Caddy，并申请 HTTPS 证书。

## 五、数据库时间规则

- 所有界面时间按 `Asia/Shanghai` 处理。
- 预约结束可以填写 `24:00`，数据库存储为次日 `00:00`。
- 一个预约不得跨自然日。
- 30 分钟为最小时间单位。
- 状态为 `booked` 或 `in_use` 的预约参与冲突检查。
- 实际使用时长为“开始使用”到“结束使用”的分钟数。

## 六、建议的上线流程

1. 管理员使用邮箱注册并以主账号登录。
2. 管理员在“成员授权”中审批已培训成员。
3. 成员通过`预约日历`提交预约。
4. 使用前后点击`开始使用`和`结束使用`。
5. 管理员按日期导出使用统计，用于后续授权、培训和设备管理。

## 安全注意事项

- 不要把 Supabase `service_role` key 放进前端或 GitHub。
- 生产环境应使用 HTTPS。
- 建议定期备份 Supabase 数据库。
- 成员停用后保留历史预约记录，不直接删除账号。








