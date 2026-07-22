var ResearchRetrieverFullText;

function log(message) {
  Zotero.debug(`Research Retriever Full Text: ${message}`);
}

function install() {
  log("Installed");
}

async function startup() {
  await Zotero.initializationPromise;
  ResearchRetrieverFullText = {
    observerID: null,
    pendingItemIDs: new Set(),
    timer: null,

    start() {
      this.observerID = Zotero.Notifier.registerObserver(
        this,
        ["item"],
        "research-retriever-full-text",
      );
      log("Watching for newly added rr:managed items");
    },

    stop() {
      if (this.observerID) {
        Zotero.Notifier.unregisterObserver(this.observerID);
        this.observerID = null;
      }
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
      }
      this.pendingItemIDs.clear();
    },

    notify(event, type, ids) {
      if (event !== "add" || type !== "item") {
        return;
      }
      for (let id of ids) {
        this.pendingItemIDs.add(id);
      }
      if (this.timer) {
        clearTimeout(this.timer);
      }
      this.timer = setTimeout(() => this.processPendingItems(), 2000);
    },

    async processPendingItems() {
      this.timer = null;
      let ids = [...this.pendingItemIDs];
      this.pendingItemIDs.clear();
      let items = await Zotero.Items.getAsync(ids);
      let eligible = [];
      for (let item of items) {
        if (!item || !item.isRegularItem() || !this.isManaged(item)) {
          continue;
        }
        if (await this.hasPDFAttachment(item)) {
          continue;
        }
        eligible.push(item);
      }
      if (!eligible.length) {
        return;
      }
      log(`Looking for full text for ${eligible.length} item(s)`);
      try {
        await Zotero.Attachments.addAvailableFiles(eligible);
      } catch (error) {
        Zotero.logError(error);
      }
    },

    isManaged(item) {
      return item.getTags().some(({ tag }) => tag === "rr:managed");
    },

    async hasPDFAttachment(item) {
      let attachments = await Zotero.Items.getAsync(item.getAttachments());
      return attachments.some(
        attachment =>
          attachment.isAttachment()
          && attachment.attachmentContentType === "application/pdf",
      );
    },
  };
  ResearchRetrieverFullText.start();
}

function shutdown() {
  ResearchRetrieverFullText?.stop();
  ResearchRetrieverFullText = undefined;
  log("Stopped");
}

function uninstall() {
  log("Uninstalled");
}
