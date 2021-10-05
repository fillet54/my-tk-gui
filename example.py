import gui

def state_converter(var):
    return 'normal' if var.get() else 'disabled'

# CUSTOM COMPONENTS
###################

gui.register('input',"""\
    <group padx="5" pady="5">
    	<label side='left' padx='5'><text>{label}</text></label>
        <entry id='{id}' bg='gold' expand='true' state='disabled'/>
    </group>
""", defaults=dict(id='', label='label'))


# MAIN GUI
##########

root, bindings = gui.realize_root("""\
<form>
    <input id='entry' label='entry:'/>
    <checkbutton id='enable'><text>enable</text></checkbutton>
    <group>
         <button id='ok' text='OK' />
         <button id='cancel' text='Cancel' />
    </group>
</form>
""")

def on_ok(b):
    entry = b['entry'].get()
    checkbutton = b['enable'].get()
    print("Will Upload Form: [entry=>%s] [checkbutton=>%d]" % (entry, checkbutton))

def on_enable_change(var):
    bindings['entry_widget'].config(state=state_converter(var))

bindings['on_ok_click'] = on_ok
bindings['on_enable_change'](on_enable_change)
bindings['on_cancel_click'] = root.destroy

root.mainloop()
