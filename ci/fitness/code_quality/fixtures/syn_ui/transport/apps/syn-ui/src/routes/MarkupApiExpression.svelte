<!-- PROBE: an /api/ URL built in a markup expression -->
<script lang="ts">
  let { id }: { id: string } = $props()
</script>
<a href={`/api/v1/executions/${id}`}>raw</a>
