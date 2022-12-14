import gui

def state_converter(var):
    return 'normal' if var.get() else 'disabled'

# CUSTOM COMPONENTS
###################

gui.register('accentcheckbutton', """\
    <checkbutton id="{id}" text="{text}" style='Secondary.TCheckbutton' />
""", defaults=dict(id='', text=''))

gui.register('switch', """\
    <checkbutton id='{id}' text='{label}' style='Switch.TCheckbutton' />
        """, defaults=(dict(id='', label='')))
# MAIN GUI

##########

root, bindings = gui.realize_root("""\
<form padx="10" pady="10">
    <group side="left">
        <group label="Checkbuttons">
            <accentcheckbutton id='chk_unchecked' text="Unchecked" padx="5" pady="10"/>
            <checkbutton id='chk_checked' text="Checked" padx="5" pady="10"/>
            <checkbutton id='chk_third_state' text="Third State" padx="5" pady="10"/>
            <checkbutton id='chk_disabled' text="Disabled" state='disabled' padx="5" pady="10"/>
        </group>
        <separator />
        <group label="RadioButtons">
            <radiobutton id='rdio_unchecked' text="Unchecked" padx="5" pady="10"/>
            <radiobutton id='rdio_checked' text="Checked" padx="5" pady="10"/>
            <radiobutton id='rdio_disabled' text="Disabled" state='disabled' padx="5" pady="10"/>
        </group>
    </group>

    <group side="left">
        <entry id="entry" />
        <spinbox id="spinbox" />
        <combobox id="combobox" />
        <combobox state="readonly" />
        <button text="Button" />
        <button text="Accent Button" />
        <switch label='text'/>
    </group>
</form>
""")

bindings['chk_checked'].set(True)
bindings['chk_third_state'].set(True)
bindings['chk_third_state_widget'].state(['alternate'])

bindings['rdio_checked'].set(True)

bindings['entry'].set('Entry')
bindings['spinbox_widget'].insert(0, 'Combobox')

root.mainloop()

#class NotifyHandler(object):
#    def __init__(self):
#        self.__listeners = []
#
#    def on_notify_property_changed(self, property_name):
#        remove = False
#        for ref in self.__listeners:
#            listener = ref()
#            if listener is not None:
#                listener(property_name)
#            else:
#                remove = True
#        
#        # Remove any dead refs
#        if remove:
#            self.__listeners[:] = [ref for ref in self.__listeners if ref()]
#
#    def register_property_change_listener(self, listener):
#        self.listeners.append(weakref.ref(listener))
#
#class ModelView(NotifyPropertyChange):
#
#    @binding
#    def name(self):
#        return self.__name
#
#    name = Binding()


