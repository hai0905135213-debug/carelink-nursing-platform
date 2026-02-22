/* analytics.js
   渲染仪表盘与订单页面的图表
   Safari 兼容：不使用 async/await，改用 Promise .then() 链
*/
(function () {
  function showOverlay(el, text) { if (!el) return; el.textContent = text; el.style.display = 'flex'; }
  function hideOverlay(el) { if (!el) return; el.style.display = 'none'; }
  function showLoader(el) { if (!el) return; el.style.display = 'block'; }
  function hideLoader(el) { if (!el) return; el.style.display = 'none'; }

  function createLineChart(ctx, labels, data) {
    var g = ctx.createLinearGradient(0, 0, 0, 200);
    g.addColorStop(0, 'rgba(13,148,136,0.18)');
    g.addColorStop(1, 'rgba(13,148,136,0.02)');
    return new Chart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: [{ label: '分钟', data: data, borderColor: '#0d9488', backgroundColor: g, fill: true, tension: 0.24, pointRadius: 4, pointHoverRadius: 6 }] },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: { mode: 'index', intersect: false, callbacks: { label: function (ctx) { return ctx.dataset.label + ': ' + ctx.formattedValue + ' 分钟'; } } }
        },
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: {
          x: { display: true, ticks: { maxRotation: 45, minRotation: 0 } },
          y: { beginAtZero: true, title: { display: true, text: '分钟' } }
        }
      }
    });
  }

  function createPieChart(ctx, labels, data) {
    var colors = ['#0d9488', '#ff8e6b', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];
    var total = data.reduce(function (a, b) { return a + b; }, 0) || 1;
    return new Chart(ctx, {
      type: 'pie',
      data: { labels: labels, datasets: [{ data: data, backgroundColor: colors.slice(0, labels.length) }] },
      options: { responsive: true, plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: function (ctx) { return ctx.label + ': ' + ctx.formattedValue + ' 分钟 (' + Math.round(ctx.parsed / total * 100) + '%)'; } } } } }
    });
  }

  function movingAverage(values, win) {
    if (win <= 1) return values.slice();
    var out = [];
    for (var i = 0; i < values.length; i++) {
      var start = Math.max(0, i - win + 1);
      var slice = values.slice(start, i + 1);
      var sum = 0;
      for (var j = 0; j < slice.length; j++) sum += slice[j];
      out.push(Math.round(sum / slice.length));
    }
    return out;
  }

  function fillDateRange(labels, values, days) {
    days = days || 14;
    var today = new Date();
    var end = today;
    if (labels.length) {
      var t = Date.parse(labels[labels.length - 1]);
      if (!isNaN(t)) end = new Date(t);
    }
    var outLabels = [], outValues = [];
    for (var i = days - 1; i >= 0; i--) {
      var d = new Date(end); d.setDate(end.getDate() - i);
      var y = d.getFullYear();
      var m = String(d.getMonth() + 1).padStart(2, '0');
      var dd = String(d.getDate()).padStart(2, '0');
      var key = y + '-' + m + '-' + dd;
      outLabels.push(key);
      var idx = labels.indexOf(key);
      outValues.push(idx >= 0 ? values[idx] : 0);
    }
    return [outLabels, outValues];
  }

  function addDownloadButton(canvas, chart) {
    try {
      var wrap = canvas.parentElement;
      if (!wrap) return;
      if (wrap.querySelector('.chart-download')) return;
      var btn = document.createElement('button');
      btn.innerText = '下载图片';
      btn.className = 'btn btn-sm btn-outline-secondary ms-2 chart-download';
      btn.style.position = 'absolute'; btn.style.right = '12px'; btn.style.top = '8px';
      btn.onclick = function () {
        var url = chart.toBase64Image();
        var a = document.createElement('a'); a.href = url; a.download = 'chart.png'; a.click();
      };
      wrap.appendChild(btn);
    } catch (e) { }
  }

  // 渲染 analytics 页面
  function renderAnalytics() {
    var payload = window.ANALYTICS_PAYLOAD;
    if (!payload) return;
    if (typeof Chart === 'undefined') return;
    tryRenderAnalytics(payload);
  }

  function tryRenderAnalytics(payload) {
    var lineEl = document.getElementById('lineChart');
    var polarEl = document.getElementById('polarChart');
    if (lineEl) {
      var overlay = document.getElementById('lineChart-overlay');
      var loader = document.getElementById('lineChart-loader');
      showLoader(loader);
      var labels = payload.daily_labels || [];
      var values = payload.daily_values || [];
      var filled = fillDateRange(labels, values, 14);
      labels = filled[0]; values = filled[1];
      var ma7 = movingAverage(values, 7);
      var chart = createLineChart(lineEl.getContext('2d'), labels, values);
      try { chart.data.datasets.push({ label: '7日均值', data: ma7, borderColor: '#ff8e6b', backgroundColor: 'rgba(255,142,107,0.08)', fill: true, tension: 0.24, pointRadius: 0 }); chart.update(); } catch (e) { }
      hideLoader(loader); hideOverlay(overlay);
      addDownloadButton(lineEl, chart);
    }
    if (polarEl) {
      var overlay2 = document.getElementById('polarChart-overlay');
      var loader2 = document.getElementById('polarChart-loader');
      showLoader(loader2);
      var labels2 = payload.worker_labels || [];
      var values2 = payload.worker_values || [];
      if (!labels2.length || values2.reduce(function (a, b) { return a + b; }, 0) === 0) {
        createPieChart(polarEl.getContext('2d'), ['无数据'], [1]);
      } else {
        var total = values2.reduce(function (a, b) { return a + b; }, 0) || 1;
        var pctLabels = labels2.map(function (l, i) { return l + ' (' + Math.round(values2[i] / total * 100) + '%)'; });
        var chart2 = createPieChart(polarEl.getContext('2d'), pctLabels, values2);
        addDownloadButton(polarEl, chart2);
      }
      hideLoader(loader2); hideOverlay(overlay2);
    }
  }

  // 渲染单订单页面：用 Promise .then() 链代替 async/await（Safari 兼容）
  function renderOrder(orderId) {
    var durEl = document.getElementById('durationsChart');
    var durOverlay = document.getElementById('durationsChart-overlay');
    var durLoader = document.getElementById('durationsChart-loader');
    var shareEl = document.getElementById('workerShareChart');
    var shareOverlay = document.getElementById('workerShareChart-overlay');
    var shareLoader = document.getElementById('workerShareChart-loader');

    if (durEl) {
      showLoader(durLoader);
      fetch('/api/order/' + orderId + '/durations')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var labels = Array.isArray(data) ? data.map(function (d) { return d.date; }) : [];
          var values = Array.isArray(data) ? data.map(function (d) { return Number(d.minutes) || 0; }) : [];
          if (!labels.length) {
            var today = new Date();
            for (var i = 13; i >= 0; i--) {
              var d = new Date(today); d.setDate(d.getDate() - i);
              labels.push(d.toISOString().slice(0, 10));
              values.push(0);
            }
          }
          var chart = createLineChart(durEl.getContext('2d'), labels, values);
          var ma7 = movingAverage(values, 7);
          try { chart.data.datasets.push({ label: '7日均值', data: ma7, borderColor: '#ff8e6b', backgroundColor: 'rgba(255,142,107,0.08)', fill: true, tension: 0.24, pointRadius: 0 }); chart.update(); } catch (e) { }
          hideLoader(durLoader); hideOverlay(durOverlay);
          addDownloadButton(durEl, chart);
        })
        .catch(function () {
          hideLoader(durLoader);
          showOverlay(durOverlay, '图表加载失败');
        });
    }

    if (shareEl) {
      showLoader(shareLoader);
      fetch('/api/order/' + orderId + '/worker-shares')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var labels = Array.isArray(data) ? data.map(function (d) { return d.worker || '未知'; }) : [];
          var values = Array.isArray(data) ? data.map(function (d) { return d.minutes || 0; }) : [];
          var ctx = shareEl.getContext('2d');
          if (!labels.length || values.reduce(function (a, b) { return a + b; }, 0) === 0) {
            new Chart(ctx, { type: 'pie', data: { labels: ['无数据'], datasets: [{ data: [1], backgroundColor: ['#e5e7eb'] }] }, options: { responsive: true, plugins: { legend: { position: 'bottom' } } } });
          } else {
            var total = values.reduce(function (a, b) { return a + b; }, 0) || 1;
            var pctLabels = labels.map(function (l, i) { return l + ' (' + Math.round(values[i] / total * 100) + '%)'; });
            new Chart(ctx, { type: 'pie', data: { labels: pctLabels, datasets: [{ data: values, backgroundColor: ['#0d9488', '#ff8e6b', '#10b981', '#f59e0b', '#8b5cf6'] }] }, options: { responsive: true, plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: function (ctx) { return ctx.label + ' ' + ctx.formattedValue + ' 分钟'; } } } } } });
          }
          hideLoader(shareLoader); hideOverlay(shareOverlay);
        })
        .catch(function () {
          hideLoader(shareLoader);
          showOverlay(shareOverlay, '图表加载失败');
        });
    }
  }

  function runRender() {
    try { renderAnalytics(); } catch (e) { }
    try {
      if (window.ORDER_PAYLOAD && window.ORDER_PAYLOAD.orderId) {
        renderOrder(window.ORDER_PAYLOAD.orderId);
      }
    } catch (e) { }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runRender);
  } else {
    runRender();
  }
})();
