<!-- PROBE: a string hides code from a line-comment stripper (review 1) -->
<script lang="ts">
  const s = ' // '; fetch('/x')
</script>
<p>{s}</p>
