- migrate test cases into a harbor-tasks repo

ideas:
- multi-step conversation evals
- replayable environment
- fault injection
- skill triggering timing benchmark
- tell user what traces causing the failure, failure attribution
    - failure pattern across jobs (common patterns)
    - hard coded failure pattern
    - xiaoyi categories (System API call, operate APP)
    - how to better utilize the relationship between eval result and trajectory pattern

tasks
- 10 high-quality 0-1 generation
- all high-quality openclaw bench tasks

- integrate clawbench project and analyze it

- xiaoyi trace analysis POC
    - critical failure
    - what might causing a failure when using xiaoyi tools?
    - re-ran 147 using minimax, 分析不同模型 trajectory (kimi/minimax)
    - paper summary, the core idea of TAR, ATIF to TAR
    - paper result reproduce on Harbor ATIF
    - analyze xiaoyi(taichu) tool list to new categories
    - remove unrelateded categories(like refactor)
    - analyze pinchbench trajectories for openclaw patterns
    - add other methodolgies for failure attribution (tool call failure, skill related failure like load skill too many times or too late)(agentic trace analysis, skill-based)
    - think what xiaoyi-specific failure pattern would be
    - design trace analysis interface