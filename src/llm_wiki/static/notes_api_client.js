(function (window) {
  function api(path, options = {}) {
    const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    const config = Object.assign({ credentials: "same-origin", headers }, options);
    return fetch(path, config).then(async (response) => {
      if (response.status === 401) {
        window.location.href = "/admin/dashboard/login?next_path=/notes";
        throw new Error("인증이 필요합니다");
      }
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const payload = await response.json();
          detail = payload.detail || detail;
        } catch (error) {}
        const error = new Error(detail);
        error.status = response.status;
        throw error;
      }
      return response.json();
    });
  }

  function jsonOptions(method, payload) {
    return {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    };
  }

  window.LlmWikiApiClient = {
    api,
    jsonOptions
  };
})(window);
