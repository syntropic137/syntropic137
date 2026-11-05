//! Hidden oracle for case `markdown-portability` (bead dreamship-v0-181.3.10).
//!
//! Black box: it calls only the interface the case's task states, and never
//! assumes a file layout inside the exported folder. Copied into
//! `ws_packages/data-layer/tests/` at score time; the agent never sees it.

use std::fs;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use dream_ship_data_layer::SpaceSnapshot;
use dream_ship_domain::{
    Compartment, CompartmentType, Goal, GoalPriority, Signal, SignalPriority,
};
use tempfile::tempdir;
use uuid::Uuid;

fn at() -> DateTime<Utc> {
    DateTime::from_timestamp(1_790_000_000, 0).unwrap()
}

fn space() -> SpaceSnapshot {
    SpaceSnapshot {
        signals: vec![
            Signal::new(Uuid::from_u128(0x21), Some(Uuid::from_u128(0xa1)), at(), "oracle filed note", SignalPriority::Critical).unwrap(),
            Signal::new(Uuid::from_u128(0x22), None, at(), "oracle inbox note", SignalPriority::Incidental).unwrap(),
        ],
        compartments: vec![
            Compartment::new(Uuid::from_u128(0xa1), CompartmentType::Project, "Oracle Project").unwrap(),
            Compartment::new(Uuid::from_u128(0xa2), CompartmentType::Area, "Oracle Area").unwrap(),
        ],
        goals: vec![Goal::new(Uuid::from_u128(0xc9), "Oracle goal title", GoalPriority::P0).unwrap()],
    }
}

fn by_id(mut s: SpaceSnapshot) -> SpaceSnapshot {
    s.signals.sort_by_key(|x| x.id);
    s.compartments.sort_by_key(|x| x.id);
    s.goals.sort_by_key(|x| x.id);
    s
}

fn files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in fs::read_dir(&dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                stack.push(path);
            } else {
                out.push(path);
            }
        }
    }
    out
}

fn file_containing(root: &Path, needle: &str) -> PathBuf {
    let hits: Vec<PathBuf> = files(root)
        .into_iter()
        .filter(|p| fs::read_to_string(p).is_ok_and(|t| t.contains(needle)))
        .collect();
    assert_eq!(hits.len(), 1, "exactly one exported file must carry {needle:?}, found {hits:?}");
    hits.into_iter().next().unwrap()
}

#[test]
fn export_then_import_round_trips_every_entity() {
    let tmp = tempdir().unwrap();
    let out = tmp.path().join("export");
    let snap = space();
    snap.export_markdown(&out).unwrap();
    assert_eq!(by_id(SpaceSnapshot::import_markdown(&out).unwrap()), by_id(snap));
}

#[test]
fn every_exported_file_is_plain_utf8_markdown() {
    let tmp = tempdir().unwrap();
    let out = tmp.path().join("export");
    space().export_markdown(&out).unwrap();
    let all = files(&out);
    assert!(all.len() >= 5, "one file per entity at least, got {all:?}");
    for path in &all {
        assert_eq!(path.extension().and_then(|e| e.to_str()), Some("md"), "{path:?} is not markdown");
        fs::read_to_string(path).unwrap_or_else(|e| panic!("{path:?} is not UTF-8: {e}"));
    }
    for text in ["oracle filed note", "Oracle Project", "Oracle goal title"] {
        file_containing(&out, text);
    }
}

#[test]
fn an_edit_made_outside_the_app_is_imported() {
    let tmp = tempdir().unwrap();
    let out = tmp.path().join("export");
    space().export_markdown(&out).unwrap();
    let goal = file_containing(&out, "Oracle goal title");
    let edited = fs::read_to_string(&goal).unwrap().replace("Oracle goal title", "Edited by hand");
    fs::write(&goal, edited).unwrap();
    let back = SpaceSnapshot::import_markdown(&out).unwrap();
    let g = back.goals.iter().find(|g| g.id == Uuid::from_u128(0xc9)).unwrap();
    assert!(format!("{g:?}").contains("Edited by hand"), "edit lost: {g:?}");
}

#[test]
fn an_empty_space_round_trips() {
    let tmp = tempdir().unwrap();
    let out = tmp.path().join("export");
    SpaceSnapshot::default().export_markdown(&out).unwrap();
    assert_eq!(SpaceSnapshot::import_markdown(&out).unwrap(), SpaceSnapshot::default());
}
