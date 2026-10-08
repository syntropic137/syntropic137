import '@syn137/skyline-themes/all.css'
import '@syn137/skyline-svelte-v5/styles.css'
import './app.css'

import { mount } from 'svelte'
import { configureClient } from '@syn137/syn-ui-data'
import App from './App.svelte'

configureClient({ fixtures: import.meta.env.VITE_SYN_FIXTURES === '1' })

const target = document.getElementById('app')
if (!target) throw new Error('#app missing from index.html')

export default mount(App, { target })
