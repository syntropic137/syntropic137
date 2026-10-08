//! The tray icon: the base app icon with a status dot.

use tauri::image::Image;

use super::live_state::LiveState;

const BASE_ICON: &[u8] = include_bytes!("../../icons/32x32.png");

/// The base app icon with a status dot in the bottom-right corner.
pub fn icon_for(state: LiveState) -> tauri::Result<Image<'static>> {
    let base = Image::from_bytes(BASE_ICON)?;
    let (w, h) = (base.width(), base.height());
    let mut rgba = base.rgba().to_vec();
    let r = (w.min(h) as f32) * 0.22; // dot radius
    let ring = (w.min(h) as f32) * 0.07; // dark outline so the dot reads on any tray
    let cx = w as f32 - r - ring - 0.5;
    let cy = h as f32 - r - ring - 0.5;
    let [dr, dg, db] = state.rgb();
    for y in 0..h {
        for x in 0..w {
            let dx = x as f32 + 0.5 - cx;
            let dy = y as f32 + 0.5 - cy;
            let d = (dx * dx + dy * dy).sqrt();
            let i = ((y * w + x) * 4) as usize;
            if d <= r {
                rgba[i..i + 4].copy_from_slice(&[dr, dg, db, 255]);
            } else if d <= r + ring {
                rgba[i..i + 4].copy_from_slice(&[11, 15, 20, 255]);
            }
        }
    }
    Ok(Image::new_owned(rgba, w, h))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dot_is_drawn() {
        let img = icon_for(LiveState::Live).unwrap();
        let (w, h) = (img.width(), img.height());
        // a pixel inside the dot, near the bottom-right corner
        let x = w - (w as f32 * 0.29) as u32;
        let y = h - (h as f32 * 0.29) as u32;
        let i = ((y * w + x) * 4) as usize;
        assert_eq!(&img.rgba()[i..i + 4], &[46, 213, 115, 255]);
    }
}
