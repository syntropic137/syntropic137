<!-- PROBE: "<!--" and "-->" inside an event handler fool a regex comment stripper (review 2) -->
<button onclick={() => { const a = '<!--'; fetch('/x'); const b = '-->'; return a + b }}>go</button>
