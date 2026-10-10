<!-- PROBE: title="<script>" in markup fools a regex script splitter (review 2) -->
<p title="<script>">x</p>
<button onclick={() => fetch('/x')}>go</button>
<p title="</script>">y</p>
