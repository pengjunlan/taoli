import { showToast } from "./utils.js";

function syncItemVisibility(item) {
  const searchHidden = item.dataset.searchHidden === "true";
  const paginationHidden = item.dataset.paginationHidden === "true";
  item.style.display = searchHidden || paginationHidden ? "none" : "";
}

function getPaginationContainers(root = document) {
  if (!root) return [];

  const containers = [];
  if (root.matches?.("[data-pagination-items]")) {
    containers.push(root);
  }

  containers.push(...root.querySelectorAll?.("[data-pagination-items]"));
  return containers;
}

export function bindPrototypeActions() {
  document.querySelectorAll("[data-prototype-action]").forEach((element) => {
    element.addEventListener("click", () => {
      showToast(element.dataset.prototypeAction || "功能开发中");
    });
  });
}

export function bindToggleGroups() {
  document.querySelectorAll("[data-toggle-group]").forEach((group) => {
    group.querySelectorAll(".tab-chip").forEach((button) => {
      button.addEventListener("click", () => {
        group.querySelectorAll(".tab-chip").forEach((item) => item.classList.remove("is-active"));
        button.classList.add("is-active");
      });
    });
  });
}

export function bindTableSearch() {
  document.querySelectorAll("[data-table-search]").forEach((input) => {
    const selector = input.getAttribute("data-table-search");
    const table = selector ? document.querySelector(selector) : null;
    if (!table) return;

    const rows = Array.from(table.querySelectorAll("tbody tr")).filter(
      (row) => !row.classList.contains("table-empty-row"),
    );

    input.addEventListener("input", () => {
      const keyword = input.value.trim().toLowerCase();
      rows.forEach((row) => {
        const visible = row.textContent.toLowerCase().includes(keyword);
        row.dataset.searchHidden = visible ? "false" : "true";
        syncItemVisibility(row);
      });

      table.dispatchEvent(new CustomEvent("prototype:filter-change"));
    });
  });
}

export function bindListPagination(root = document) {
  getPaginationContainers(root).forEach((container) => {
    if (container.__paginationCleanup) return;

    const itemSelector = container.dataset.paginationItems;
    if (!itemSelector) return;

    const items = Array.from(container.querySelectorAll(itemSelector)).filter(
      (item) => !item.classList.contains("table-empty-row"),
    );
    if (!items.length) return;

    const pageSize = Math.max(1, Number(container.dataset.pageSize || 5));
    let currentPage = 1;

    const footerHost = container.closest(".table-wrap, .alert-list") || container;
    const footer = document.createElement("div");
    footer.className = "pagination-bar";
    footer.hidden = true;
    footer.innerHTML = `
      <div class="pagination-bar__meta"></div>
      <div class="pagination-bar__actions">
        <button class="table-action table-action--primary pagination-bar__more" type="button">更多</button>
        <button class="table-action pagination-bar__prev" type="button">上一页</button>
        <div class="pagination-bar__pages"></div>
        <button class="table-action pagination-bar__next" type="button">下一页</button>
      </div>
    `;
    footerHost.insertAdjacentElement("afterend", footer);

    const meta = footer.querySelector(".pagination-bar__meta");
    const moreButton = footer.querySelector(".pagination-bar__more");
    const prevButton = footer.querySelector(".pagination-bar__prev");
    const nextButton = footer.querySelector(".pagination-bar__next");
    const pages = footer.querySelector(".pagination-bar__pages");

    const render = () => {
      const filteredItems = items.filter((item) => item.dataset.searchHidden !== "true");
      const totalItems = filteredItems.length;

      if (!totalItems || totalItems <= pageSize) {
        items.forEach((item) => {
          item.dataset.paginationHidden = "false";
          syncItemVisibility(item);
        });
        footer.hidden = true;
        return;
      }

      const totalPages = Math.ceil(totalItems / pageSize);
      currentPage = Math.min(currentPage, totalPages);

      items.forEach((item) => {
        item.dataset.paginationHidden = "true";
      });

      const startIndex = (currentPage - 1) * pageSize;
      const endIndex = startIndex + pageSize;
      filteredItems.slice(startIndex, endIndex).forEach((item) => {
        item.dataset.paginationHidden = "false";
      });
      items.forEach(syncItemVisibility);

      meta.textContent = `显示 ${startIndex + 1}-${Math.min(endIndex, totalItems)} / 共 ${totalItems} 条`;
      moreButton.hidden = currentPage >= totalPages;
      prevButton.disabled = currentPage === 1;
      nextButton.disabled = currentPage >= totalPages;

      pages.innerHTML = "";
      for (let page = 1; page <= totalPages; page += 1) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `table-action pagination-bar__page${page === currentPage ? " is-active" : ""}`;
        button.textContent = String(page);
        button.addEventListener("click", () => {
          currentPage = page;
          render();
        });
        pages.appendChild(button);
      }

      footer.hidden = false;
    };

    moreButton.addEventListener("click", () => {
      currentPage += 1;
      render();
    });

    prevButton.addEventListener("click", () => {
      currentPage -= 1;
      render();
    });

    nextButton.addEventListener("click", () => {
      currentPage += 1;
      render();
    });

    const handleFilterChange = () => {
      currentPage = 1;
      render();
    };

    container.addEventListener("prototype:filter-change", handleFilterChange);

    container.__paginationCleanup = () => {
      container.removeEventListener("prototype:filter-change", handleFilterChange);
      footer.remove();
      delete container.__paginationCleanup;
    };

    render();
  });
}

export function refreshListPagination(root = document) {
  getPaginationContainers(root).forEach((container) => {
    if (container.__paginationCleanup) {
      container.__paginationCleanup();
    }
  });

  bindListPagination(root);
}
