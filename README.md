# CLIHub (gzcli)

一个父指令统一网关：各团队将 HTTP 接口通过配置文件注册为 `gzcli` 的子指令，
鉴权、调用、更新等横切逻辑由 `gzcli` 统一屏蔽。

```bash
gzcli init --conf conf.yaml          # 注册子指令配置
gzcli img_detect obj_detect --img a.jpg   # 调用团队接口
```

详细设计见项目内讨论，MVP 阶段配置 Schema 见 `examples/conf.yaml`。
