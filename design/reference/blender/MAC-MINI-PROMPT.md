Render the Syntropic137 Blender hero on the Mac mini. Don't render anything on this laptop: it's busy.

Folder: ~/Code/Syntropic137/handoffs/20261009_syntropic137_skyline-redesign/blender/
(build_hero.py, render_mac_mini.sh, encode_web.sh, README.md)

1. Find the Mac mini's ssh host (check ~/.ssh/config, or `tailscale status`). Confirm Blender is installed there (default /Applications/Blender.app/Contents/MacOS/Blender; otherwise set BLENDER=...) and that ffmpeg is available (`brew install ffmpeg` on the mini if not).
2. Copy the folder over:
   rsync -a --exclude renders ~/Code/Syntropic137/handoffs/20261009_syntropic137_skyline-redesign/blender/ <mini>:~/syn137-blender/
3. Start the render in the background so it survives the ssh session:
   ssh <mini> 'cd ~/syn137-blender && nohup ./render_mac_mini.sh > render.log 2>&1 &'
   It renders the hero, banner and mark stills at 256 samples on the GPU (Metal), plus a 5-second animation at 1920x1080, then encodes the web files.
4. Check on it every few minutes (`ssh <mini> 'tail -5 ~/syn137-blender/render.log; ls ~/syn137-blender/renders/frames | wc -l'`). Expect 120 frames. If a step fails, read render.log, fix the cause, and re-run only that step.
5. When it finishes, bring the results back without overwriting the cloud previews:
   rsync -a <mini>:~/syn137-blender/renders/final/ ~/Code/Syntropic137/handoffs/20261009_syntropic137_skyline-redesign/blender/renders/final/
   rsync -a <mini>:~/syn137-blender/renders/web/   ~/Code/Syntropic137/handoffs/20261009_syntropic137_skyline-redesign/blender/renders/web/
6. Report:
   - the file sizes of hero-poster.avif/.webp, hero.webm and hero.mp4 (targets: poster under about 150 KB, clip under about 1.5 MB; if they're over, re-encode with a higher crf or smaller width via `W=1600 ./encode_web.sh`);
   - the render times;
   - whether the faint grey rectangle behind the S is still there (see README known issues).
   Open the hero still so I can look at it.
