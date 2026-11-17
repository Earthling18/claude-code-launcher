import React from 'react';
import { createRoot } from 'react-dom/client';
import App from '../../src/App';
localStorage.setItem('local_deps_ok', '1');
const output = document.createElement('output');
output.id = 'navigation-proof';
output.style.cssText = 'position:fixed;bottom:0;left:0;z-index:9999;background:#fff;color:#111;font:11px monospace;padding:4px';
document.body.append(output);
let previousListVisible = false, remembered = 0, returned = false;
const proof = { returns: 0, firstFrame: 0, expected: 0, blankFrames: 0, wrongFrames: 0 };
function sample() {
  const isList = location.pathname === '/local', el = document.querySelector<HTMLElement>('[data-testid="project-list-scroll"]');
  if (isList && el && !previousListVisible && remembered > 0) {
    returned = true; proof.returns++; proof.expected = remembered; proof.firstFrame = el?.scrollTop ?? -1;
  }
  if (returned && isList && el) {
    if (!el?.querySelector('[data-project-id]')) proof.blankFrames++;
    if (Math.abs((el?.scrollTop ?? -1) - proof.expected) > 1) proof.wrongFrames++;
  }
  if (isList && el) remembered = el.scrollTop;
  previousListVisible = Boolean(el);
  output.textContent = JSON.stringify(proof);
  requestAnimationFrame(sample);
}
document.addEventListener('wheel', () => { returned = false; }, true);
requestAnimationFrame(sample);
createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
