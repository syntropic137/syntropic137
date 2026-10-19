<!-- PROBE: a string hides a dynamic import from a comment stripper (review 1) -->
<script lang="ts">
  const s = ' /* '; import('@syn137/syn-ui-data'); const e = ' */ '
</script>
<p>{s}{e}</p>
