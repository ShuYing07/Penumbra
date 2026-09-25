f = "D:/StockAIPredictor/app/ui/main_window.py"
c = open(f, encoding="utf-8").read()
# 加import
c = c.replace(
    "from app.ui.watchlist_tab import WatchlistTab\n",
    "from app.ui.watchlist_tab import WatchlistTab\nfrom app.ui.stock_directory_tab import StockDirectoryTab\n"
)
# 加实例化
c = c.replace(
    "self.debate_tab = DebateTab()\n",
    "self.debate_tab = DebateTab()\n        self.stock_dir_tab = StockDirectoryTab()\n"
)
# 加tab
c = c.replace(
    'self.tabs.addTab(self.debate_tab, "多空辩论")\n',
    'self.tabs.addTab(self.debate_tab, "多空辩论")\n        self.tabs.addTab(self.stock_dir_tab, "股票大全")\n'
)
open(f, "w", encoding="utf-8").write(c)
print("OK")
