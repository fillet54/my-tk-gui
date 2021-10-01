import gui

# CUSTOM COMPONENTS
###################

gui.register('input',"""\
    <group padx="5" pady="5">
    	<label side='left' padx='5'><text>{label}</text></label>
        <entry id='{id}' bg='gold' expand='true' />
    </group>
""", defaults=dict(id='', label='label'))


# MAIN GUI
##########

root, bindings = gui.realize_root("""\
<form>
    <input id='entry' label='entry:'/>
    <checkbutton id='checkbutton'><text>checkbutton</text></checkbutton>
    <group>
         <button id='ok' text='OK' />
         <button id='cancel' text='Cancel' />
    </group>
</form>
""")

def on_ok(b):
    entry = b['entry'].get()
    checkbutton = b['checkbutton'].get()
    print("Will Upload Form: [entry=>%s] [checkbutton=>%d]" % (entry, checkbutton))


bindings['on_ok_click'] = on_ok
bindings['on_cancel_click'] = root.destroy

root.mainloop()
