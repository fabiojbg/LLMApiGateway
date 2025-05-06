# Fault-Tolerant LLM Gateway
---
<div align="center" style="text-align: center;">
 <img alt="LLM Gateway" src="https://img.shields.io/badge/LLM-Gateway-blue?style=flat" />&nbsp;
 <a href="https://openrouter.ai"><img alt="OpenRouter" src="https://img.shields.io/badge/OpenRouter-AI-blue?style=flat" /></a>
 &nbsp;
 <a href="https://www.paypal.com/donate/?business=G47L9N4UW8C2C&no_recurring=1&item_name=Thank+you+%21%21%21&currency_code=USD"><img alt="Download" src="https://img.shields.io/badge/Donate-😊-yellow?style=flat" /></a>
  
</div>
<br>

Stop having API call failures to your LLM models, no matter which provider you are using.
This project can replace providers to give you an almost foolproof LLM model provider.
LLM Gateway works as an OpenAI-compatible LLM API provider with advanced fallback support for models in case of response failures.
Use it with code agents like Cline, RooCode, or even with your applications as a regular OpenAI API-compatible LLM provider.

## Features

- **Fault Tolerance**: Automatically falls back to alternative models if the primary model fails
- **Model Rotation**: Optionally rotates through available models for each API key, distributing load and cost across providers
- **Flexible Configuration**: Configure fallback sequences and rotation settings per model

## Gateway endpoints

  - `/v1/models` - Like v1, just lists available models <br/><br/>
  - `/v1/chat/completions` - OpenAI compatible API that routes calls to other providers with fallback in case of call failure.<br><br>
  **HOT FEATURE:**: This endpoint allows you to create a sequence of fallback models to be called in case of failure, with support for retries. For example, if a model response fails, the gateway can retry the same model or automatically move to the next model in the fallback sequence, and so on. The model's sequence can consist of different models and different providers. For instance, the first model in the sequence could be deepseek-chat from OpenRouter, and the gateway can be configured to fall back to gpt-4o from OpenAI in case of failure. This fallback sequence can be of any size and must be configured in the file `models_fallback_rules.json`.

## Configuration

Create a `.env` file from the example .env.example:
```bash
cp .env.example .env
```
>[!IMPORTANT]
>These are the files you will have to prepare before use:<br>
>`.env` - main configurations and API keys<br>
> `providers.json` - configure your providers. A lot is already set here<br>
> `models_fallback_rules.json` - the main magic happens here. Set the gateway models with their rules. See the examples in the sections below<br>


 **.env** configuration example:
 ```
# This gateway must have its own API key that clients must use to access it
# Use it in http header as "Authorization: Bearer <ThisGatewayApiKey>"
GATEWAY_API_KEY=<ThisGatewayApiKey>

# Maximum number of log files to keep (older files will be deleted)
LOG_FILE_LIMIT=15

# Enable/disable logging of chat messages to the /logs folder (true/false). 
# Useful for debugging
LOG_CHAT_ENABLED=false

# The default fallback provider to use when the model received is not recognized 
# by this gateway in the fallback rules.
FALLBACK_PROVIDER=openrouter

# The keys of your providers. Used in the providers.json
# Fill the ones you want to use or add more if you need
APIKEY_OPENROUTER=<your_openrouter_api_key>
APIKEY_REQUESTY=<your_requesty_api_key>
APIKEY_OPENAI=<your_openai_api_key>
APIKEY_NEBIUS=<your_nebius_api_key>
APIKEY_TOGETHER=<your_together_api_key>
APIKEY_KLUSTERAI=<your_klusterai_api_key>
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GATEWAY_API_KEY` | Fixed API key clients must use to access this gateway | *required* |
| `LOG_FILE_LIMIT` | Maximum number of chat log files to keep | `15` |
| `LOG_CHAT_ENABLED` | Enable detailed chat logging to `logs/` directory | `true` |
| `FALLBACK_PROVIDER` | Default provider name for `/v2` if no rule matches | `openrouter` |
| `APIKEY_PROVIDERNAME` | API key for a specific provider (e.g., `APIKEY_OPENROUTER`) | *required for providers in providers.json* |

## Providers Example (`providers.json`)
Here, you must define your providers. These providers must be compatible with the OpenAI API format.
The `apikey` fields are keys to the environment variables with the actual key value.

```json
[
    {
        "openrouter":
        {
            "baseUrl" : "https://openrouter.ai/api/v1",            
            "apikey" : "APIKEY_OPENROUTER"  //environment variable name that holds the provider apykey
        }
    },
    {
        "nebius":
        {
            "baseUrl" : "https://api.studio.nebius.ai/v1",            
            "apikey" : "APIKEY_NEBIUS" //environment variable name that holds the provider apykey
        }
    },
    {
        "openai":
        {
            "baseUrl" : "https://api.openai.com/v1",            
            "apikey" : "APIKEY_OPENAI" //environment variable name that holds the provider apykey
        }
    }
]
```


### Fallback Rules JSON Example (`models_fallback_rules.json`):

#### Simple fallback 
In this mode (`rotate_models=false`), the gateway always starts with the first model in each request and falls back to the next ones in case of failures.<br>
Retries can be also configured for each model.
```json
[
    {
        "gateway_model_name": "llmgateway/free-stack", // this gateway model to be referenced
        "rotate_models" : "false", // no rotation, always starts with the first model and falls back to the next in case of failure
        "fallback_models" :
        [
            { 
                "provider": "openrouter",
                "model" : "deepseek/deepseek-r1:free",
                "retry_delay" : 15,     // retry delay in seconds for this model in case of failure
                "retry_count" : 3,      // how many times to retry
                "providers_order" : ["Chutes", "Targon"] // Force provider order in openrouter for this model
            },
            {
                "provider": "requesty",
                "model" : "google/gemini-2.5-pro-exp-03-25"
            },
            {
                "provider": "openrouter",
                "model" : "deepseek/deepseek-chat-v3-0324:free",
                "use_provider_order_as_fallback": true, // use providers_order as fallback
                "providers_order" : ["Chutes", "Targon"] // if use_provider_order_as_fallback is true, this will be used as fallback one by one
            }
        ]                    
    }
]
```

#### Model Rotation
In this mode (`rotate_models=true`), the gateway cycles through all models between requests. This is useful when we want to utilize credits from various providers. Fallback also works in this mode in case of failures; the sequence loops back to the first model when the sequence finishes.
```json
[
    {
        // an example of a model that exists in various providers
        "gateway_model_name": "llmgateway/deepseek-v3.1", 
        "rotate_models": true,  // When true, gatweway will rotate through models between requests. Retry is ignored in this mode
        "fallback_models" :
        [
            {
                "provider": "openrouter",
                "model" : "deepseek/deepseek-chat-v3-0324",
                "providers_order" : ["Lambda", "DeepInfra", "Nebius AI Studio"]
            },
            {
                "provider": "nebius",
                "model": "deepseek-ai/DeepSeek-V3-0324"
            },
            {
                "provider": "requesty",
                "model" : "novita/deepseek/deepseek-v3-0324"
            }
        ]                    
    }
]    
```

#### Custom Parameters and Headers Injection/Override
For any model, you can inject or override custom headers or body parameters by specifing it in the rules.
Here is an example of using grok-3-mini-beta from xAI that accepts an `reasoning_effort` parameter.
Custom headers a also available if needed.
```json
[
    {
        // an example of a model with custom body
        "gateway_model_name": "llmgateway/xAI", 
        "fallback_models" :
        [
            {
                "provider": "xAI",
                "model" : "grok-3-mini-beta",                
                "custom_body_params" : {
                    "reasoning_effort" : "high"  // grok has this reasoning_effort parameter that can be set here
                },
                "custom_headers" : {
                    "x-param" : "demo"  // custom header example
                }
            }
        ]                    
    }       
]    
```


**Failover and Rotation Logic:**

When a request comes to `/v1/chat/completions`:

1.  The gateway finds the rule matching the requested `model` in the models_fallback_rules.json file.
2.  If the model is not found in the rules, the gateway routes the request to the fallback provider defined by the FALLBACK_PROVIDER environment variable. The name of the model will be the same as received.
3.  If model rotation is enabled (`"rotate_models": true`), the gateway selects the next model in the sequence for each request.
4.  If model rotation is disabled (`"rotate_models": false` or ommited), the gateway always starts with the first model in the sequence and only falls back to the next ones in case of failure.
5.  (OpenRouter only) If the current model has the parameter `use_provider_order_as_fallback=true` and has a list of `providers_order`, the gateway will use only the first provider in the list and fall back to the next ones only in case of failures. This way, the fallback is treated by this gateway and not OpenRouter.
6.  If the selected model fails, the gateway tries the next models in the sequence until one succeeds.
7.  Return an HTTP 503 error if none of the called models succeed.

**Model Rotation:**

The model rotation feature allows you to distribute requests across multiple providers even when there are no failures. This is useful for:

- Load balancing across different providers
- Avoiding rate limits on individual providers
- Reducing costs by distributing usage

The rotation state is tracked per API key and gateway model combination, ensuring consistent behavior for each client.

## Running

## With pip

Install Python dependencies once if you're using pip:
```bash
pip install -r requirements.txt
```
and run
```bash
python llmgateway.py
```


### With UV (preferable)
if uv is installed, simply do:
```bash
uv run llmgateway.py
```


## Using with Cline Example
You can use it with Cline, RooCode, or any other code agent.
You just need to configure it as an OpenAI-compatible provider.
Here is an example of using this gateway with Cline, set to use the model `'llmgateway/free-stack'`, which only uses models free of charge, as configured in the example above.

![Cline example](./images/cline-example.png)