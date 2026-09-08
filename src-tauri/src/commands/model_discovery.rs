use super::ModelProbeResult;
use crate::models::ModelApiFormat;
use serde_json::Value;
use std::collections::HashSet;
use std::time::{Duration, Instant};

const MAX_PAGES: usize = 100;
const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(60);

fn discovery_url(base_url: &str, api_format: ModelApiFormat) -> String {
    let base_url = base_url.trim().trim_end_matches('/');
    match api_format {
        ModelApiFormat::AnthropicMessages => format!("{}/v1/models", base_url),
        ModelApiFormat::OpenaiResponses => format!("{}/models", base_url),
    }
}

fn model_ids(value: &Value) -> Result<Vec<String>, String> {
    let items = value
        .get("data")
        .or_else(|| value.get("models"))
        .unwrap_or(value)
        .as_array()
        .ok_or("服务返回了无法识别的模型列表格式，可手动填写模型名称后测试")?;
    let ids: Vec<String> = items
        .iter()
        .filter_map(|item| item.as_str().or_else(|| item.get("id")?.as_str()))
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .map(str::to_string)
        .collect();
    if !items.is_empty() && ids.is_empty() {
        return Err("模型列表中没有可识别的模型 ID，可手动填写模型名称后测试".to_string());
    }
    Ok(ids)
}

fn next_cursor(value: &Value, ids: &[String]) -> Result<Option<String>, String> {
    let has_more = value
        .get("has_more")
        .or_else(|| value.get("hasMore"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !has_more {
        return Ok(None);
    }
    let cursor = value
        .get("last_id")
        .or_else(|| value.get("lastId"))
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .map(str::to_string)
        .or_else(|| ids.last().cloned())
        .ok_or("服务提示还有更多模型，但未返回有效的分页游标")?;
    Ok(Some(cursor))
}

async fn fetch_page(request: reqwest::RequestBuilder) -> Result<(u16, Value), (u16, String)> {
    let response = request.send().await.map_err(|error| {
        let message = if error.is_timeout() {
            "获取模型列表超时（20s）".to_string()
        } else if error.is_connect() {
            "无法连接模型服务，请检查地址和网络".to_string()
        } else {
            "模型列表请求失败，请重试".to_string()
        };
        (0, message)
    })?;
    let status = response.status().as_u16();
    if !response.status().is_success() {
        let error = match status {
            401 | 403 => format!(
                "模型列表鉴权失败（HTTP {}），请检查当前 API Key 的权限",
                status
            ),
            404 | 405 => format!(
                "该地址未提供模型列表接口（HTTP {}），可手动填写模型名称后测试",
                status
            ),
            _ => format!("获取模型列表失败（HTTP {}）", status),
        };
        return Err((status, error));
    }
    let value = response.json::<Value>().await.map_err(|error| {
        let message = if error.is_timeout() {
            "读取模型列表超时（20s）"
        } else {
            "服务未返回有效的 JSON 模型列表，可手动填写模型名称后测试"
        };
        (status, message.to_string())
    })?;
    Ok((status, value))
}

pub(super) async fn discover_models(
    base_url: &str,
    token: &str,
    api_format: ModelApiFormat,
) -> ModelProbeResult {
    let start = Instant::now();
    let mut result = ModelProbeResult::default();
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .build()
    {
        Ok(client) => client,
        Err(_) => {
            result.error = Some("构造 HTTP client 失败".to_string());
            return result;
        }
    };
    let url = discovery_url(base_url, api_format);
    let token = token.trim();
    let mut cursor: Option<String> = None;
    let mut seen_cursors = HashSet::new();
    let mut seen_models = HashSet::new();

    for page in 0..MAX_PAGES {
        let mut request = client.get(&url).header("accept", "application/json");
        if matches!(api_format, ModelApiFormat::AnthropicMessages) {
            request = request.header("anthropic-version", "2023-06-01");
        }
        if !token.is_empty() {
            request = request.bearer_auth(token);
            if matches!(api_format, ModelApiFormat::AnthropicMessages) {
                request = request.header("x-api-key", token);
            }
        }
        if let Some(cursor) = &cursor {
            // Anthropic pagination: https://platform.claude.com/docs/en/api/models/list
            // Compatible services can serialize response fields as lastId/hasMore.
            request = request.query(&[("after_id", cursor)]);
        }
        let remaining = DISCOVERY_TIMEOUT.saturating_sub(start.elapsed());
        let response = tokio::time::timeout(remaining, fetch_page(request))
            .await
            .unwrap_or_else(|_| Err((0, "获取完整模型列表超时（60s）".to_string())));
        let (status, value) = match response {
            Ok(response) => response,
            Err((status, error)) => {
                if page == 0 {
                    result.status = status;
                }
                result.error = Some(error);
                break;
            }
        };
        result.status = status;
        let ids = match model_ids(&value) {
            Ok(ids) => ids,
            Err(error) => {
                result.error = Some(error);
                break;
            }
        };
        for id in &ids {
            if seen_models.insert(id.clone()) {
                result.models.push(id.clone());
            }
        }
        result.ok = true;
        cursor = match next_cursor(&value, &ids) {
            Ok(None) => break,
            Ok(Some(cursor)) if seen_cursors.insert(cursor.clone()) => Some(cursor),
            Ok(Some(_)) => {
                result.error = Some("服务重复返回同一分页游标，已停止继续获取".to_string());
                break;
            }
            Err(error) => {
                result.error = Some(error);
                break;
            }
        };
        if page + 1 == MAX_PAGES {
            result.error = Some("模型列表超过 100 页，已停止继续获取".to_string());
        }
    }
    if result.ok {
        result.warning = result
            .error
            .take()
            .map(|error| format!("模型列表未完整获取：{}", error));
    }
    result.latency_ms = start.elapsed().as_millis() as u64;
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    fn server(
        pages: Vec<(&'static str, u16, &'static str)>,
    ) -> (String, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = std::thread::spawn(move || {
            for (path, status, body) in pages {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut bytes = Vec::new();
                let mut buffer = [0; 4096];
                while !bytes.windows(4).any(|part| part == b"\r\n\r\n") {
                    let size = stream.read(&mut buffer).unwrap();
                    assert!(size > 0);
                    bytes.extend_from_slice(&buffer[..size]);
                }
                let request = String::from_utf8_lossy(&bytes);
                assert!(request.starts_with(&format!("GET {} HTTP/", path)));
                assert!(request
                    .to_ascii_lowercase()
                    .contains("authorization: bearer test-key"));
                write!(stream, "HTTP/1.1 {} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", status, body.len(), body).unwrap();
            }
        });
        (format!("http://{}", address), handle)
    }

    #[tokio::test]
    async fn collects_all_pages_and_deduplicates_ids() {
        let (url, server) = server(vec![
            (
                "/v1/models",
                200,
                r#"{"data":[{"id":"first"},{"id":"shared"}],"has_more":true,"last_id":"page/1"}"#,
            ),
            (
                "/v1/models?after_id=page%2F1",
                200,
                r#"{"data":[{"id":"shared"},{"id":"last"}],"has_more":false}"#,
            ),
        ]);
        let result = discover_models(&url, "test-key", ModelApiFormat::AnthropicMessages).await;
        server.join().unwrap();
        assert!(result.ok);
        assert_eq!(result.models, ["first", "shared", "last"]);
        assert!(result.warning.is_none());
    }

    #[tokio::test]
    async fn supports_camel_case_pagination_and_stops_repeated_cursors() {
        let (url, server) = server(vec![
            (
                "/v1/models",
                200,
                r#"{"data":[{"id":"first"}],"hasMore":true,"lastId":"first"}"#,
            ),
            (
                "/v1/models?after_id=first",
                200,
                r#"{"data":[{"id":"first"}],"hasMore":true,"lastId":"first"}"#,
            ),
        ]);
        let result = discover_models(&url, "test-key", ModelApiFormat::AnthropicMessages).await;
        server.join().unwrap();
        assert!(result.ok);
        assert_eq!(result.models, ["first"]);
        assert!(result.warning.unwrap().contains("重复"));
    }

    #[tokio::test]
    async fn preserves_partial_list_when_a_later_page_fails() {
        let (url, server) = server(vec![
            (
                "/models",
                200,
                r#"{"data":[{"id":"first"}],"has_more":true,"last_id":"first"}"#,
            ),
            ("/models?after_id=first", 503, "{}"),
        ]);
        let result = discover_models(&url, "test-key", ModelApiFormat::OpenaiResponses).await;
        server.join().unwrap();
        assert!(result.ok);
        assert_eq!(result.models, ["first"]);
        assert!(result.warning.unwrap().contains("503"));
        assert!(result.error.is_none());
    }

    #[tokio::test]
    async fn rejects_invalid_json_instead_of_reporting_an_empty_success() {
        let (url, server) = server(vec![("/models", 200, "<html>Login</html>")]);
        let result = discover_models(&url, "test-key", ModelApiFormat::OpenaiResponses).await;
        server.join().unwrap();
        assert!(!result.ok);
        assert!(result.error.unwrap().contains("JSON"));
    }

    #[test]
    fn accepts_list_shapes_but_not_display_names_or_invalid_ids() {
        for value in [
            serde_json::json!({"data": [{"id": "a"}, {"id": 42}, {"name": "display name"}, {"id": "b"}]}),
            serde_json::json!({"models": ["a", "", "b"]}),
            serde_json::json!(["a", {"id": "b"}]),
        ] {
            assert_eq!(model_ids(&value).unwrap(), ["a", "b"]);
        }
        assert!(model_ids(&serde_json::json!({})).is_err());
        assert!(model_ids(&serde_json::json!({"data": []}))
            .unwrap()
            .is_empty());
        assert!(model_ids(&serde_json::json!({"data": [{"id": 42}]})).is_err());
    }
}
