//! syn137:// deep links -> app routes.
//!
//! Accepted forms (host or path style, both seen across OS launchers):
//!   syn137://executions/<id>    -> /executions/<id>
//!   syn137:///executions/<id>   -> /executions/<id>
//!   syn137://executions         -> /executions
//! Anything else is ignored. Ids are restricted to a conservative charset so a
//! link can never smuggle a query, fragment or `..` into the router.

use url::Url;

pub const SCHEME: &str = "syn137";

fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id != "."
        && id != ".."
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ':'))
}

/// Map a deep link URL to an in-app route, or None if it is not one we serve.
pub fn route_for(raw: &str) -> Option<String> {
    let url = Url::parse(raw.trim()).ok()?;
    if !url.scheme().eq_ignore_ascii_case(SCHEME) {
        return None;
    }
    let mut segs: Vec<String> = Vec::new();
    if let Some(host) = url.host_str() {
        if !host.is_empty() {
            segs.push(host.to_string());
        }
    }
    if let Some(path) = url.path_segments() {
        segs.extend(path.filter(|s| !s.is_empty()).map(str::to_string));
    }
    match segs.as_slice() {
        [area] if area.eq_ignore_ascii_case("executions") => Some("/executions".to_string()),
        [area, id] if area.eq_ignore_ascii_case("executions") && valid_id(id) => {
            Some(format!("/executions/{id}"))
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::route_for;

    #[test]
    fn host_style() {
        assert_eq!(
            route_for("syn137://executions/exec_01J9Z").as_deref(),
            Some("/executions/exec_01J9Z")
        );
    }

    #[test]
    fn path_style_and_trailing_slash() {
        assert_eq!(
            route_for("syn137:///executions/abc-123/").as_deref(),
            Some("/executions/abc-123")
        );
    }

    #[test]
    fn list() {
        assert_eq!(
            route_for("syn137://executions").as_deref(),
            Some("/executions")
        );
        assert_eq!(
            route_for("SYN137://Executions/").as_deref(),
            Some("/executions")
        );
    }

    #[test]
    fn rejects_other_schemes_and_routes() {
        assert_eq!(route_for("https://executions/abc"), None);
        assert_eq!(route_for("syn137://workflows/abc"), None);
        assert_eq!(route_for("syn137://executions/a/b"), None);
        assert_eq!(route_for("not a url"), None);
    }

    #[test]
    fn rejects_unsafe_ids() {
        assert_eq!(route_for("syn137://executions/..%2F..%2Fsecret"), None);
        assert_eq!(route_for("syn137://executions/a%20b"), None);
        // the URL parser collapses dot segments; ".." can never reach the router as an id
        assert_ne!(
            route_for("syn137://executions/..").as_deref(),
            Some("/executions/..")
        );
        assert_eq!(route_for("syn137:///executions/a/../../x"), None);
        // query and fragment are dropped, never forwarded
        assert_eq!(
            route_for("syn137://executions/abc?x=1#y").as_deref(),
            Some("/executions/abc")
        );
    }
}
