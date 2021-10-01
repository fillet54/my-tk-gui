import gui


root, bindings = gui.realize_root("""\
<form>
    <group padx="5" pady="5">
    	<label side='left' padx='5'><text>entry:</text></label>
    	<entry id='entry' width='30' bg='gold' expand='true' />
    </group>
    <checkbutton id='checkbutton'><text>checkbutton</text></checkbutton>
    <group>
         <button id='ok' text='OK' />
         <button id='cancel' text='Cancel' />
    </group>
</form>
""")

def on_ok():
    entry = bindings['entry'].get()
    checkbutton = bindings['checkbutton'].get()
    print("Will Upload Form: [entry=>%s] [checkbutton=>%d]" % (entry, checkbutton))


bindings['on_ok_click'] = on_ok
bindings['on_cancel_click'] = root.destroy

root.mainloop()
