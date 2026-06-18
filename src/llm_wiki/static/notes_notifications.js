(function (window) {
  function createNotificationControls(dependencies) {
    const api = dependencies.api;
    const jsonOptions = dependencies.jsonOptions;
    const getConfig = dependencies.getConfig;
    const setConfig = dependencies.setConfig;
    const clearActiveNotification = dependencies.clearActiveNotification;
    const loadOverview = dependencies.loadOverview;
    const setSaveState = dependencies.setSaveState;
    const elements = dependencies.elements || {};
    const notificationStatus = elements.notificationStatus;
    const enablePwaButton = elements.enablePwaButton;
    const testNotificationButton = elements.testNotificationButton;

    function renderNotificationControls() {
      const config = getConfig();
      const pwa = config && config.pwa ? config.pwa : {};
      const telegram = config && config.telegram ? config.telegram : {};
      const supportsPwa = "serviceWorker" in navigator
        && "PushManager" in window
        && "Notification" in window
        && window.isSecureContext;
      const permission = "Notification" in window ? Notification.permission : "unsupported";
      const statusParts = [];
      if (!config) {
        statusParts.push("알림 상태를 확인하지 않았습니다.");
      } else if (!supportsPwa) {
        statusParts.push("이 브라우저에서는 PWA Push를 사용할 수 없습니다.");
      } else if (!pwa.available) {
        statusParts.push("브라우저 알림 서버 키가 아직 설정되지 않았습니다.");
      } else if (permission === "granted") {
        statusParts.push(`브라우저 알림 사용 가능 / 구독 ${pwa.subscription_count || 0}개`);
      } else if (permission === "denied") {
        statusParts.push("브라우저에서 알림 권한이 차단되었습니다.");
      } else {
        statusParts.push("브라우저 알림을 켤 수 있습니다.");
      }
      statusParts.push(telegram.available ? "텔레그램 사용 가능" : "텔레그램 미설정");
      notificationStatus.textContent = statusParts.join(" / ");
      enablePwaButton.disabled = !supportsPwa || !pwa.available || permission === "denied";
      enablePwaButton.textContent = permission === "granted" ? "브라우저 알림 갱신" : "브라우저 알림 켜기";
      const canTestPwa = Boolean(pwa.available && permission === "granted" && (pwa.subscription_count || 0) > 0);
      const canTestTelegram = Boolean(telegram.available);
      testNotificationButton.disabled = !config || (!canTestPwa && !canTestTelegram);
    }

    function loadNotificationConfig() {
      return api("/api/notifications/config").then((config) => {
        setConfig(config);
        renderNotificationControls();
      }).catch((error) => {
        setConfig(null);
        notificationStatus.textContent = error.message || "알림 상태 확인 실패";
        renderNotificationControls();
      });
    }

    function urlBase64ToUint8Array(base64String) {
      const padding = "=".repeat((4 - base64String.length % 4) % 4);
      const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
      const rawData = window.atob(base64);
      const outputArray = new Uint8Array(rawData.length);
      for (let index = 0; index < rawData.length; index += 1) {
        outputArray[index] = rawData.charCodeAt(index);
      }
      return outputArray;
    }

    async function enablePwaNotifications() {
      try {
        if (!getConfig()) await loadNotificationConfig();
        const config = getConfig();
        const pwa = config && config.pwa ? config.pwa : {};
        if (!pwa.available || !pwa.public_key) {
          setSaveState("브라우저 알림 서버 설정 필요", "conflict");
          renderNotificationControls();
          return;
        }
        if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window) || !window.isSecureContext) {
          setSaveState("브라우저 알림을 지원하지 않습니다", "conflict");
          renderNotificationControls();
          return;
        }
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
          setSaveState("알림 권한이 허용되지 않았습니다", "conflict");
          renderNotificationControls();
          return;
        }
        enablePwaButton.disabled = true;
        enablePwaButton.textContent = "등록 중";
        const registration = await navigator.serviceWorker.register("/sw.js");
        let subscription = await registration.pushManager.getSubscription();
        if (!subscription) {
          subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(pwa.public_key)
          });
        }
        await api("/api/notifications/pwa-subscriptions", jsonOptions("POST", subscription.toJSON()));
        setSaveState("브라우저 알림 켜짐", "saved");
        await loadNotificationConfig();
      } catch (error) {
        setSaveState(error.message || "브라우저 알림 등록 실패", "conflict");
        renderNotificationControls();
      }
    }

    function sendTestNotification() {
      const config = getConfig();
      if (!config) return;
      const channels = [];
      const pwa = config.pwa || {};
      const telegram = config.telegram || {};
      if ("Notification" in window && Notification.permission === "granted" && (pwa.subscription_count || 0) > 0) channels.push("pwa");
      if (telegram.available) channels.push("telegram");
      if (channels.length === 0) {
        setSaveState("사용 가능한 알림 채널이 없습니다", "conflict");
        return;
      }
      testNotificationButton.disabled = true;
      setSaveState("테스트 알림 전송 중", "saving");
      return api("/api/notifications/test", jsonOptions("POST", { channels })).then((result) => {
        const failed = (result.results || []).filter((item) => item.status !== "sent");
        const details = failed.map((item) => item.error || `${item.channel || "알림"} 실패`).join(" / ");
        setSaveState(
          failed.length > 0 ? `알림 실패: ${details.slice(0, 90)}` : "테스트 알림 전송됨",
          failed.length > 0 ? "conflict" : "saved"
        );
        return loadNotificationConfig();
      }).catch((error) => {
        setSaveState(error.message || "테스트 알림 실패", "conflict");
      }).finally(() => {
        renderNotificationControls();
      });
    }

    function cancelNotificationDelivery(deliveryId) {
      if (!deliveryId) return;
      setSaveState("알림 취소 중", "saving");
      return api("/api/notifications/deliveries/" + encodeURIComponent(deliveryId) + "/cancel", jsonOptions("POST", {})).then(() => {
        setSaveState("알림 취소됨", "saved");
        return loadOverview();
      }).catch((error) => {
        setSaveState(error.message || "알림 취소 실패", "conflict");
      });
    }

    function deleteNotificationDelivery(deliveryId) {
      if (!deliveryId) return;
      if (!window.confirm("이 알림 이력을 삭제할까요?")) return;
      setSaveState("알림 삭제 중", "saving");
      return api("/api/notifications/deliveries/" + encodeURIComponent(deliveryId) + "/delete", jsonOptions("POST", {})).then(() => {
        clearActiveNotification();
        setSaveState("알림 삭제됨", "saved");
        return loadOverview();
      }).catch((error) => {
        setSaveState(error.message || "알림 삭제 실패", "conflict");
      });
    }

    return {
      cancelNotificationDelivery,
      deleteNotificationDelivery,
      enablePwaNotifications,
      loadNotificationConfig,
      renderNotificationControls,
      sendTestNotification,
      urlBase64ToUint8Array
    };
  }

  window.LlmWikiNotifications = {
    createNotificationControls
  };
})(window);
