"""Expense tracker: the whole window, bound to expenses.ExpensesViewModel.

There is no event-handling code in this file. Try:
  * typing in the form -- the error message and the Add button follow along
  * selecting a row and editing it -- the list, totals and budget bar update
  * searching / filtering -- the count and filtered total update
  * the dark mode switch
"""

import gui
from expenses import sample

VIEW = """
<form padding="16" theme="{theme}">
  <row fill="x">
    <label text="Expenses" font="-size 18 -weight bold" />
    <switch text="Dark mode" checked="{dark_mode}" side="right" padx="0" />
  </row>

  <row fill="both" expand="1" pady="12 0">
    <!-- Packed first so a narrow window shrinks the list, not the sidebar. -->
    <group side="right" fill="y" padx="16 0" spacing="12">
      <group label="New expense" padding="12">
        <fields>
          <entry label="Description" text="{form.description}" on_return="{add}" />
          <combobox label="Category" text="{form.category}" values="{categories}" state="readonly" />
          <entry label="Amount" text="{form.amount_text}" on_return="{add}" />
        </fields>
        <label text="{form.error}" foreground="#d83b01" />
        <accentbutton text="Add expense" command="{add}" fill="none" anchor="e" />
      </group>

      <group label="Selected" padding="12" context="{selected}">
        <fields>
          <entry label="Description" text="{description}" />
          <combobox label="Category" text="{category}" values="{$root.categories}" state="readonly" />
          <spinbox label="Amount" text="{amount|number}" from="0" to="100000" increment="5" />
        </fields>
        <button text="Delete" command="{$root.remove}" fill="none" anchor="e" />
      </group>

      <group label="Budget" padding="12">
        <fields>
          <spinbox label="Monthly" text="{budget|number}" from="0" to="100000" increment="100" />
        </fields>
        <progressbar value="{budget_used}" maximum="100" />
        <label text="{budget_status}" />
        <label text="Spent {total|money} in total" />
      </group>
    </group>

    <group side="left" fill="both" expand="1">
      <row fill="x">
        <entry text="{search}" width="24" on_escape="{clear_filters}" />
        <combobox text="{category_filter}" values="{filter_options}" state="readonly" width="10" />
        <button text="Clear" command="{clear_filters}" />
      </row>
      <treeview items="{visible}" selection="{selected}" height="12"
                fill="both" expand="1" on_delete="{remove}">
        <column key="description" heading="Description" width="220" />
        <column key="category" heading="Category" width="100" />
        <column key="amount" heading="Amount" format="money" width="100" anchor="e" />
      </treeview>
      <row fill="x">
        <label text="{summary}" />
        <label text="{visible_total|money}" side="right" padx="0" />
      </row>
    </group>
  </row>
</form>
"""

if __name__ == "__main__":
    gui.run(VIEW, sample(), title="Expenses", minsize=(900, 560))
