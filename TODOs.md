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

tasks
- 10 high-quality 0-1 generation
- all high-quality openclaw bench tasks


- xiaoyi trace analysis POC
    - paper summary
    - paper result reproduce
    - analyze xiaoyi(taichu) tool list to new categories
    - remove unrelateded categories(like refactor)
    - analyze pinchbench trajectories for openclaw patterns
    - add other methodolgies for failure attribution (tool call failure, skill related failure like load skill too many times or too late)(agentic trace analysis, skill-based)
    - think what xiaoyi-specific failure pattern would be
    - design trace analysis interface