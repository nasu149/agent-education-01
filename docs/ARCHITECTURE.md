# Architecture

```text
Browser
  |
  v
httpd :8088
  |
  v
Tomcat / Java Servlet
  |
  v
PostgreSQL

Ordinary health checker
  |
  | failure
  v
LangGraph
  |
  +--> investigate <----+
  |       |             |
  |       v             |
  |     ToolNode -------+
  |       |
  |       v
  |      judge
  |       |
  |       +---- manual/none ----> report
  |       |
  |       v
  |    approval (interrupt)
  |       |
  |   approve/reject
  |       |
  |       v
  |    remediate
  |       |
  |       v
  |     verify
  |       |
  +-------+ on failure
          |
          v
        report
```

## Boundary taught by the exercise

- Health monitoring is deterministic software, not an LLM task.
- `investigate` is agentic because the next observation depends on previous observations.
- `ToolNode` executes only read-only tools chosen by the LLM.
- `judge` converts the investigation into an explicit structured decision.
- `approval` is a security boundary, not a decorative node.
- `remediate` owns state-changing tools. Those tools are not bound to the LLM.
- `verify` re-observes the environment after action.
- MCP is the tool connection layer. It is not the Agent itself.
