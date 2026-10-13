<!-- PROBE: a string hides code from a block-comment stripper (review 1) -->
<script lang="ts">
  const s = ' /* '; fetch('/x'); const e = ' */ '
</script>
<p>{s}{e}</p>
