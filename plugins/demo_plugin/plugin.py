from plugin_system import PluginBase
class Plugin(PluginBase):
    metadata={'name':'demo_plugin','version':'0.0.1','permissions':['data_access'],'author':'t','description':'d'}
    def register_tools(self, ctx):
        ctx.register_tool('demo_ping', lambda: 'pong')
