# Product Context

## Problem Space
- LLM API failures disrupt AI agent workflows and application stability.
- Managing multiple LLM providers individually is complex (API keys, rate limits, costs).
- Need for a unified, reliable interface to various LLM models.

## Solution
- An OpenAI-compatible gateway that abstracts provider complexity.
- Implements automatic fallback to alternative models/providers upon failure.
- Offers optional model rotation to distribute load and potentially reduce costs.

## Target Users
- Developers using AI agents (like Cline, RooCode).
- Applications requiring robust LLM integration.
- Teams managing multiple LLM provider accounts.

## User Experience Goals
- Seamless integration (drop-in replacement for OpenAI API).
- Increased reliability and uptime for LLM-dependent applications.
- Simplified configuration for complex fallback and rotation strategies.

## High-Level Workflow
```mermaid
sequenceDiagram
    participant Client
    participant Gateway
    participant PrimaryProvider as Primary Provider
    participant FallbackProvider as Fallback Provider

    Client->>+Gateway: POST /v1/chat/completions (model="llmgateway/some-stack")
    Gateway->>Gateway: Load config & rules for "llmgateway/some-stack"
    alt Rotation Enabled
        Gateway->>Gateway: Select next provider based on rotation state
    else Rotation Disabled
        Gateway->>Gateway: Select first provider in sequence
    end
    Gateway->>+PrimaryProvider: Forward request
    alt Success
        PrimaryProvider-->>-Gateway: Success response
    else Failure
        PrimaryProvider-->>-Gateway: Error response
        Gateway->>Gateway: Log failure, select next provider in fallback sequence
        Gateway->>+FallbackProvider: Retry request
        alt Success
            FallbackProvider-->>-Gateway: Success response
        else Failure
            FallbackProvider-->>-Gateway: Error response
            Gateway->>Gateway: Continue fallback or return error
        end
    end
    Gateway-->>-Client: Return final result (success or error)
```
