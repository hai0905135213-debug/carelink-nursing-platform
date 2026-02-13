/* analytics.js
   渲染仪表盘与订单页面的图表，支持懒加载、加载动画与空数据提示
*/
(function(){
  function showOverlay(overlayEl, text){ if(!overlayEl) return; overlayEl.textContent = text; overlayEl.style.display = 'flex'; }
  function hideOverlay(overlayEl){ if(!overlayEl) return; overlayEl.style.display = 'none'; }
  function showLoader(loaderEl){ if(!loaderEl) return; loaderEl.style.display = 'block'; }
  function hideLoader(loaderEl){ if(!loaderEl) return; loaderEl.style.display = 'none'; }

  function createLineChart(ctx, labels, data){
    return new Chart(ctx, {
      type: 'line', data:{ labels: labels, datasets:[{ label:'分钟', data:data, borderColor:'#1e6fff', backgroundColor:'rgba(30,111,255,0.12)', fill:true, tension:0.24 }] },
      options:{ responsive:true, plugins:{ legend:{ display:false } }, scales:{ y:{ beginAtZero:true } } }
    });
  }

  function createPolarChart(ctx, labels, data){
    const colors = ['#1e6fff','#ff7a59','#2fa66a','#f6c85f','#8f7af6','#4dd0e1'];
    return new Chart(ctx, { type:'polarArea', data:{ labels:labels, datasets:[{ data:data, backgroundColor: colors.slice(0, labels.length) }] }, options:{ responsive:true, plugins:{ legend:{ position:'bottom' } } } });
  }

  // 渲染 analytics 页面（如果有 payload）
  function renderAnalytics(){
    const payload = window.ANALYTICS_PAYLOAD;
    if(!payload) return;
    // 确保 Chart.js 已加载
    ensureChartJs().then(()=>{
      tryRenderAnalytics(payload);
    }).catch(()=>{});
    return;
  }

  function tryRenderAnalytics(payload){
    const lineEl = document.getElementById('lineChart');
    const polarEl = document.getElementById('polarChart');
    if(lineEl){
      const overlay = document.getElementById('lineChart-overlay');
      const loader = document.getElementById('lineChart-loader');
      showLoader(loader);
      const labels = payload.daily_labels || [];
      const values = payload.daily_values || [];
      if(!labels.length || labels.every(v=>!v) || !values.length || values.reduce((a,b)=>a+b,0)===0){
        hideLoader(loader); showOverlay(overlay, '暂无数据'); return;
      }
      createLineChart(lineEl.getContext('2d'), labels, values);
      hideLoader(loader); hideOverlay(overlay);
    }
    if(polarEl){
      const overlay = document.getElementById('polarChart-overlay');
      const loader = document.getElementById('polarChart-loader');
      showLoader(loader);
      const labels = payload.worker_labels || [];
      const values = payload.worker_values || [];
      if(!labels.length || values.reduce((a,b)=>a+b,0)===0){ hideLoader(loader); showOverlay(overlay, '暂无数据'); return; }
      createPolarChart(polarEl.getContext('2d'), labels, values);
      hideLoader(loader); hideOverlay(overlay);
    }
  }

  // 渲染单订单页面：通过 API 拉取数据
  async function renderOrder(orderId){
    const durEl = document.getElementById('durationsChart');
    const durOverlay = document.getElementById('durationsChart-overlay');
    const durLoader = document.getElementById('durationsChart-loader');
    const shareEl = document.getElementById('workerShareChart');
    const shareOverlay = document.getElementById('workerShareChart-overlay');
    const shareLoader = document.getElementById('workerShareChart-loader');

    if(durEl){ showLoader(durLoader); try{ await ensureChartJs(); const res = await fetch(`/api/order/${orderId}/durations`); const data = await res.json(); const labels = data.map(d=>d.date); const values = data.map(d=>d.minutes||0); if(!labels.length || values.reduce((a,b)=>a+b,0)===0){ hideLoader(durLoader); showOverlay(durOverlay,'暂无数据'); } else { createLineChart(durEl.getContext('2d'), labels, values); hideLoader(durLoader); hideOverlay(durOverlay); } } catch(e){ hideLoader(durLoader); showOverlay(durOverlay,'暂无数据'); } }

    if(shareEl){ showLoader(shareLoader); try{ await ensureChartJs(); const res = await fetch(`/api/order/${orderId}/worker-shares`); const data = await res.json(); const labels = data.map(d=>d.worker||'未知'); const values = data.map(d=>d.minutes||0); if(!labels.length || values.reduce((a,b)=>a+b,0)===0){ hideLoader(shareLoader); showOverlay(shareOverlay,'暂无数据'); } else { const ctx = shareEl.getContext('2d'); new Chart(ctx,{ type:'doughnut', data:{ labels:labels, datasets:[{ data:values, backgroundColor: ['#1e6fff','#ff7a59','#2fa66a','#f6c85f','#8f7af6'] }] }, options:{ responsive:true, plugins:{ legend:{ position:'bottom' } } } }); hideLoader(shareLoader); hideOverlay(shareOverlay); } } catch(e){ hideLoader(shareLoader); showOverlay(shareOverlay,'暂无数据'); } }
  }

  // 确保 Chart.js 可用：若已加载则立即返回，否则动态加载 CDN
  function ensureChartJs(){
    return new Promise((resolve,reject)=>{
      if(window.Chart) return resolve();
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
      s.onload = ()=>resolve(); s.onerror = ()=>reject(); document.head.appendChild(s);
    });
  }

  // 自动在 DOMContentLoaded 后触发渲染（因为脚本被 defer 注入）
  document.addEventListener('DOMContentLoaded', function(){
    try{ renderAnalytics(); }catch(e){}
    try{ if(window.ORDER_PAYLOAD && window.ORDER_PAYLOAD.orderId) renderOrder(window.ORDER_PAYLOAD.orderId); }catch(e){}
  });

})();
