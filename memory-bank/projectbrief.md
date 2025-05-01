# LLM Gateway Project Brief

## Core Purpose
Provide fault-tolerant LLM API gateway with:
- OpenAI-compatible API interface
- Automatic model fallback on failure
- Model rotation for load/cost distribution

## Key Features
- `/v1/chat/completions` endpoint with fallback sequencing
- Configurable model rotation per API key
- Multi-provider support (OpenRouter, Nebius, Together AI, etc.)
- Detailed chat logging capabilities

## Architectural Components
```mermaid
graph TD
    GW[Gateway API] --> CFG[Config Loader]
    GW --> FBR[Fallback Rules]
    GW --> PRV[Provider Manager]
    GW --> ROT[Model Rotator]
    GW --> LOG[Chat Logger]
    PRV --> OR[OpenRouter]
    PRV --> OAI[OpenAI]
    PRV --> NB[Nebius]
    PRV --> TAI[Together AI]
```    